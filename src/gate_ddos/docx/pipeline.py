import re
from copy import deepcopy
from pathlib import Path
from typing import Callable

from docx import Document
from docx.document import Document as DocxDocument
from htmldocx import HtmlToDocx
import markdown

from .styles import ensure_required_styles
from .html import postprocess_html
from .markdown import normalize_newlines
from ..models import TemplateSyntax
from ..section_store import SectionStore
from ..template_engine import TemplateEngine, build_placeholder_pattern, count_placeholders
from ..ui import CliUI


MARKDOWN_EXTENSIONS = ["extra", "sane_lists", "smarty", "md_in_html"]
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

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

_INLINE_MARKDOWN_PATTERNS = [
    re.compile(r"\[[^\]]+\]\([^)]+\)"),  # markdown links
    re.compile(r"`[^`\n]+`"),            # inline code
    re.compile(r"(\*\*|__)[^\n]+?\1"),   # bold
    re.compile(r"(^|[^*])\*[^*\n]+\*"),  # italic with *
    re.compile(r"(?<!_)_[^_\n]+_"),      # italic with _
    re.compile(r"<https?://[^>\s]+>"),   # autolink form
    re.compile(r"~~[^~\n]+~~"),          # strikethrough
    re.compile(r"\[\^[^\]]+\]"),         # footnote references
]

def _preprocess_extended_markdown(text: str) -> str:
    """Support common markdown syntaxes not enabled by default in Python-Markdown."""
    text = re.sub(r"~~([^~\n]+)~~", r"<del>\1</del>", text)
    text = re.sub(r"\^\^([^\^\n]+)\^\^", r"<sup>\1</sup>", text)
    text = re.sub(r"(?<!~)~([^~\n]+)~(?!~)", r"<sub>\1</sub>", text)
    return text


class _DocxHtmlConverter(HtmlToDocx):
    """HtmlToDocx with template-aware list styles and Table Grid tables."""

    def __init__(self, list_styles: dict[str, list[str]] | None = None):
        super().__init__()
        self._list_styles = list_styles or {"ul": ["List Bullet"], "ol": ["List Number"]}

    def set_initial_attrs(self, document=None):
        super().set_initial_attrs(document)
        self.table_style = "Table Grid"

    def _list_style_for_depth(self, list_type: str, depth: int) -> str:
        names = self._list_styles.get(list_type) or (["List Number"] if list_type == "ol" else ["List Bullet"])
        index = min(max(depth - 1, 0), len(names) - 1)
        return names[index]

    def handle_li(self):
        """Use real Word list styles from the template instead of plain text bullets."""
        list_depth = len(self.tags["list"])
        list_type = self.tags["list"][-1] if list_depth else "ul"
        style_name = self._list_style_for_depth(list_type, list_depth or 1)

        try:
            self.paragraph = self.doc.add_paragraph(style=style_name)
        except KeyError:
            fallback = "List Number" if list_type == "ol" else "List Bullet"
            self.paragraph = self.doc.add_paragraph(style=fallback)


def _available_list_styles(doc: DocxDocument, base_name: str) -> list[str]:
    """Return list style names available in the template for depth 1..9."""
    existing = {style.name for style in doc.styles}
    names: list[str] = []

    for depth in range(1, 10):
        name = base_name if depth == 1 else f"{base_name} {depth}"
        if name in existing:
            names.append(name)

    return names or [base_name]


def _iter_table_paragraphs(table):
    """Recursively yield paragraphs from a table (including nested tables)."""
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for nested in cell.tables:
                yield from _iter_table_paragraphs(nested)


def _iter_all_paragraphs(doc: DocxDocument):
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


def _is_empty_paragraph_element(el) -> bool:
    """Return True when element is a paragraph with no textual content."""
    if not el.tag.endswith("}p"):
        return False
    return not "".join(el.itertext()).strip()


def _is_list_paragraph_element(el) -> bool:
    """Return True when paragraph uses a list style (bullet/number)."""
    if not el.tag.endswith("}p"):
        return False

    style_elems = el.findall(f".//{{{W_NS}}}pStyle")
    for style in style_elems:
        val = style.get(f"{{{W_NS}}}val", "")
        if val.startswith("ListBullet") or val.startswith("ListNumber"):
            return True
    return False


def _strip_spurious_leading_blank_before_list(elements: list) -> list:
    """Remove converter-introduced blank paragraphs before a leading list."""
    i = 0
    while i < len(elements) and _is_empty_paragraph_element(elements[i]):
        i += 1

    if i > 0 and i < len(elements) and _is_list_paragraph_element(elements[i]):
        return elements[i:]
    return elements


def _new_body_elements(body, existing_ids: set[int]) -> list:
    """Return newly added body elements except section properties."""
    return [el for el in body if id(el) not in existing_ids and not el.tag.endswith("sectPr")]


def _markdown_to_elements(text: str, doc: DocxDocument) -> list:
    """Convert a Markdown string to a list of DOCX XML elements.

    Applies newline normalization and HTML post-processing for proper
    spacing and blockquote handling in the output.
    """
    text = normalize_newlines(text)
    text = _preprocess_extended_markdown(text)
    html = markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)
    html = postprocess_html(html)
    list_styles = {
        "ul": _available_list_styles(doc, "List Bullet"),
        "ol": _available_list_styles(doc, "List Number"),
    }

    body = doc.element.body
    existing = list(body)
    existing_ids = {id(el) for el in existing}
    _DocxHtmlConverter(list_styles=list_styles).add_html_to_document(html, doc)

    new_elements = _new_body_elements(body, existing_ids)
    if not new_elements:
        doc.add_paragraph("")
        new_elements = _new_body_elements(body, existing_ids)

    new_elements = _strip_spurious_leading_blank_before_list(new_elements)

    result = [deepcopy(el) for el in new_elements]
    for el in new_elements:
        body.remove(el)
    return result


def _is_simple_text(text: str) -> bool:
    """Check if text is plain enough for inline run replacement."""
    if "\n\n" in text:
        return False
    if _MARKDOWN_BLOCK_RE.search(text):
        return False
    if any(pattern.search(text) for pattern in _INLINE_MARKDOWN_PATTERNS):
        return False
    return True


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


def _insert_markdown_elements(parent, index: int, text: str, doc: DocxDocument) -> int:
    """Insert rendered markdown elements into a parent starting at index."""
    if not text.strip():
        return index

    for element in _markdown_to_elements(text, doc):
        parent.insert(index, element)
        index += 1
    return index


def _replace_in_paragraph(paragraph, replace_text: Callable[[str], str], doc: DocxDocument):
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
    _insert_markdown_elements(parent, index, updated, doc)


def _replace_paragraph_range(paragraphs, start: int, end: int, new_text: str, doc: DocxDocument):
    """Replace a range of paragraphs with new text, ensuring the placeholder spans a single DOCX block."""
    first = paragraphs[start]
    parent = first._p.getparent()
    insert_index = parent.index(first._p)

    for i in range(end, start - 1, -1):
        current = paragraphs[i]
        if current._p.getparent() is not parent:
            raise ValueError("Multi-paragraph placeholder must stay within the same DOCX block")
        parent.remove(current._p)
    _insert_markdown_elements(parent, insert_index, new_text, doc)


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


def _advance_paragraph_index(
    paragraphs: list,
    index: int,
    *,
    pattern: re.Pattern,
    replace_text: Callable[[str], str],
    doc: DocxDocument,
    syntax: TemplateSyntax,
) -> int:
    """Process one paragraph position and return the next index to inspect."""
    text = _paragraph_text(paragraphs[index])
    if not text:
        return index + 1

    if pattern.search(text):
        _replace_in_paragraph(paragraphs[index], replace_text, doc)
        return index + 1

    end, combined = _find_placeholder_span(paragraphs, index, syntax.open_delim, syntax.close_delim)
    if combined is None or end is None:
        return index + 1

    updated = replace_text(combined)
    if updated != combined:
        _replace_paragraph_range(paragraphs, index, end, updated, doc)
    return end + 1


class DocxPipeline:
    """Load a DOCX template, resolve placeholders, and write the result."""

    def __init__(
        self,
        system_prompt: str,
        syntax: TemplateSyntax,
        store: SectionStore,
        generate: Callable[[str, str], str],
        *,
        force: bool = False,
        ui: CliUI | None = None,
    ):
        self.engine = TemplateEngine(
            system_prompt, syntax, store, generate, force=force, ui=ui
        )
        self.syntax = syntax
        self.ui = ui

    def process(self, template_path: str | Path, output_path: str | Path) -> None:
        """Load *template_path*, replace all placeholders, and save to *output_path*."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        doc = Document(str(template_path))
        ensure_required_styles(doc)
        pattern = build_placeholder_pattern(self.syntax)
        paragraphs = list(_iter_all_paragraphs(doc))

        if self.ui is not None:
            combined_text = "\n".join(_paragraph_text(p) for p in paragraphs)
            self.ui.start_template(template_path, output, count_placeholders(combined_text, self.syntax))

        index = 0
        while index < len(paragraphs):
            index = _advance_paragraph_index(paragraphs, index, pattern=pattern, replace_text=self.engine.replace, doc=doc, syntax=self.syntax)

        doc.save(str(output_path))
