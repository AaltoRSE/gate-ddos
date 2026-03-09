import re
from copy import deepcopy
from pathlib import Path
from typing import Callable

from docx import Document
from htmldocx import HtmlToDocx
import markdown

from .styles import ensure_required_styles
from .html import postprocess_html
from .markdown import normalize_newlines
from ..models import TemplateSyntax
from ..section_store import SectionStore
from ..template_engine import build_placeholder_pattern, build_replacer


MARKDOWN_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "smarty"]

# Pattern to detect if text contains markdown block formatting (headers, lists, etc.)
_MARKDOWN_BLOCK_RE = re.compile(
    r"(?:^|\n)"               # start of string or newline
    r"(?:"
    r"#{1,6}\s"               # headers
    r"|[-*+]\s"               # unordered list
    r"|\d+[.)]\s"             # ordered list
    r"|>\s"                   # blockquote
    r"|```"                   # fenced code
    r"|~~~"                   # fenced code alt
    r"|\|.*\|"                # table row
    r")"
)


# DOCX Element Traversal

class _DocxHtmlConverter(HtmlToDocx):
    """HtmlToDocx with Table Grid applied to all tables."""

    def set_initial_attrs(self, document=None):
        super().set_initial_attrs(document)
        self.table_style = "Table Grid"


def _iter_table_paragraphs(table):
    """Recursively yield paragraphs from a table (including nested tables)."""
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for nested in cell.tables:
                yield from _iter_table_paragraphs(nested)


def _iter_all_paragraphs(doc: Document):
    """Yield every paragraph in the document (body, tables, headers, footers)."""
    yield from doc.paragraphs
    for table in doc.tables:
        yield from _iter_table_paragraphs(table)

    for section in doc.sections:
        for part in (section.header, section.footer):
            yield from part.paragraphs
            for table in part.tables:
                yield from _iter_table_paragraphs(table)


def _paragraph_text(paragraph) -> str:
    """Extract the full text of a paragraph from its runs."""
    if paragraph.runs:
        return "".join(run.text for run in paragraph.runs)
    return paragraph.text or ""


# Markdown to DOCX Conversion


def _markdown_to_elements(text: str, doc: Document) -> list:
    """Convert a Markdown string to a list of DOCX XML elements.

    Applies newline normalization and HTML post-processing for proper
    spacing and blockquote handling in the output.
    """
    text = normalize_newlines(text)
    html = markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)
    html = postprocess_html(html)

    body = doc.element.body
    existing = list(body)
    existing_ids = {id(el) for el in existing}
    _DocxHtmlConverter().add_html_to_document(html, doc)

    new_elements = [
        el for el in body
        if id(el) not in existing_ids and not el.tag.endswith("sectPr")
    ]
    if not new_elements: # empty markdown - insert one blank paragraph
        doc.add_paragraph("")
        new_elements = [
            el for el in body
            if id(el) not in existing_ids and not el.tag.endswith("sectPr")
        ]

    result = [deepcopy(el) for el in new_elements] # copy before removal
    for el in new_elements:
        body.remove(el)
    return result


def _is_simple_text(text: str) -> bool:
    """Check if text is simple, no markdown block formatting."""
    # Multiple lines with blank lines indicate paragraph breaks -> not simple
    if "\n\n" in text:
        return False
    # Check for markdown block patterns
    return not _MARKDOWN_BLOCK_RE.search(text)


def _replace_text_inline(paragraph, old_text: str, new_text: str) -> bool:
    """Replace text inline within paragraph runs, preserving formatting."""
    runs = paragraph.runs
    if not runs:
        return False

    # Find runs that contain the old text (may span multiple runs)
    full_text = "".join(r.text for r in runs)
    start_idx = full_text.find(old_text)
    if start_idx == -1:
        return False

    end_idx = start_idx + len(old_text)

    # Map character positions to runs
    run_starts = []
    pos = 0
    for run in runs:
        run_starts.append(pos)
        pos += len(run.text)

    # Find which runs are affected
    first_run_idx = None
    last_run_idx = None
    for i, run_start in enumerate(run_starts):
        run_end = run_start + len(runs[i].text)
        if first_run_idx is None and run_end > start_idx:
            first_run_idx = i
        if run_end >= end_idx:
            last_run_idx = i
            break

    if first_run_idx is None or last_run_idx is None:
        return False

    # Simple case: replacement is entirely within one run
    if first_run_idx == last_run_idx:
        run = runs[first_run_idx]
        local_start = start_idx - run_starts[first_run_idx]
        local_end = end_idx - run_starts[first_run_idx]
        run.text = run.text[:local_start] + new_text + run.text[local_end:]
        return True

    # Multi-run case: replacement spans multiple runs
    # Keep the first run's formatting, put replacement text there
    first_run = runs[first_run_idx]
    local_start = start_idx - run_starts[first_run_idx]

    last_run = runs[last_run_idx]
    local_end = end_idx - run_starts[last_run_idx]

    # Set first run text: text before placeholder + new text + text after (from last run)
    first_run.text = first_run.text[:local_start] + new_text + last_run.text[local_end:]

    # Clear intermediate runs and last run
    for i in range(first_run_idx + 1, last_run_idx + 1):
        runs[i].text = ""

    return True


# Paragraph Replacement Logic


def _replace_in_paragraph(paragraph, replace_text: Callable[[str], str], doc: Document):
    """Apply placeholder replacement to a single paragraph."""
    original = _paragraph_text(paragraph)
    updated = replace_text(original)
    if updated == original:
        return

    if _is_simple_text(updated) and paragraph.runs:
        if _replace_text_inline(paragraph, original, updated):
            return

    parent = paragraph._p.getparent()
    if parent is None:
        return

    index = parent.index(paragraph._p)
    parent.remove(paragraph._p)

    if not updated.strip():
        return

    for element in _markdown_to_elements(updated, doc):
        parent.insert(index, element)
        index += 1


def _replace_paragraph_range(paragraphs, start: int, end: int, new_text: str, doc: Document):
    """Replace a range of paragraphs with new text, ensuring the placeholder spans a single DOCX block."""
    first = paragraphs[start]
    parent = first._p.getparent()
    insert_index = parent.index(first._p)

    for i in range(end, start - 1, -1):
        current = paragraphs[i]
        if current._p.getparent() is not parent:
            raise ValueError("Multi-paragraph placeholder must stay within the same DOCX block")
        parent.remove(current._p)

    if not new_text.strip():
        return

    for element in _markdown_to_elements(new_text, doc):
        parent.insert(insert_index, element)
        insert_index += 1


def _find_placeholder_span(
    paragraphs: list, start: int, start_delim: str, end_delim: str
) -> tuple[int, str] | tuple[None, None]:
    """Find a placeholder that may span multiple consecutive paragraphs.

    Returns ``(end_index, combined_text)`` or ``(None, None)`` if no match.
    """
    first = paragraphs[start]
    first_text = _paragraph_text(first)
    if start_delim not in first_text:
        return None, None

    lines = [first_text]
    end = start
    found = end_delim in first_text

    while not found and end + 1 < len(paragraphs):
        next_p = paragraphs[end + 1]
        if next_p._p.getparent() is not first._p.getparent():
            break

        end += 1
        text = _paragraph_text(paragraphs[end])
        lines.append(text)
        found = end_delim in text

    if not found:
        import warnings
        combined = "\n".join(lines)
        warnings.warn(f"Unclosed placeholder starting with '{combined[:80]}...' missing '{end_delim}'", stacklevel=2)
        return None, None

    return end, "\n".join(lines)


# Public API


def process_template_docx(
    template_path: str | Path,
    output_path: str | Path,
    system_prompt: str,
    model: str,
    syntax: TemplateSyntax,
    store: SectionStore,
    generate: Callable[[str, str, str], str],
    force: bool = False,
):
    """Load a DOCX template, replace all placeholders, and save the result."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = Document(template_path)
    ensure_required_styles(doc)
    replacer = build_replacer(system_prompt, model, syntax, store, generate, force=force)
    pattern = build_placeholder_pattern(syntax)
    paragraphs = list(_iter_all_paragraphs(doc))

    index = 0
    while index < len(paragraphs):
        text = _paragraph_text(paragraphs[index])
        if not text:
            index += 1
            continue

        # Single-paragraph placeholder.
        if pattern.search(text):
            _replace_in_paragraph(paragraphs[index], replacer, doc)
            index += 1
            continue

        # Placeholder may span multiple paragraphs.
        end, combined = _find_placeholder_span(paragraphs, index, syntax.open_delim, syntax.close_delim)
        if combined is not None:
            updated = replacer(combined)
            if updated != combined:
                _replace_paragraph_range(paragraphs, index, end, updated, doc)
            index = end + 1
        else:
            index += 1

    doc.save(output_path)
