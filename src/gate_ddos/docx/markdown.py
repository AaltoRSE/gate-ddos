import re

# 3+ consecutive newlines needs sentinel for post-processing.
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# Newline before list/table line - upgrade to double newline to ensure block parsing.
BLOCK_STARTER_RE = re.compile(r"(?<!\n)\n(?=[ \t]*(?:[-*+][ \t]|\d+[.)][ \t]|\|))")
LIST_OR_TABLE_LINE_RE = re.compile(r"[ \t]*(?:[-*+][ \t]|\d+[.)][ \t]|\|)")

# Lone newline in prose excludes newlines before # and > which can interrupt
# a paragraph on their own, and list/table markers handled above.
SINGLE_NEWLINE_RE = re.compile(
    r"(?<!\n)\n(?!\n)"
    r"(?![ \t]*(?:[#>]|[-*+][ \t]|\d+[.)][ \t]|\|))"
)

# Matches fenced code blocks (``` or ~~~).
FENCED_CODE_RE = re.compile(r"(`{3,}|~{3,})[^\n]*\n(.*?)\1", re.DOTALL)


def _expand_extra_newlines(m: re.Match) -> str:
    """Replace a run of 3+ newlines with 2 plus an EXTRA_NL:N sentinel for postprocessing."""
    extra = len(m.group(0)) - 2
    return f"\n\n<!-- EXTRA_NL:{extra} -->\n\n"


def _upgrade_block_starters(chunk: str) -> str:
    """Upgrade lone newlines before list/table lines to double newlines."""

    def _maybe_upgrade(m: re.Match) -> str:
        pos = m.start()
        prev_nl = chunk.rfind("\n", 0, pos)
        prev_line = chunk[prev_nl + 1 : pos] if prev_nl >= 0 else chunk[:pos]
        if LIST_OR_TABLE_LINE_RE.match(prev_line):  # already inside the block
            return "\n"
        return "\n\n"

    return BLOCK_STARTER_RE.sub(_maybe_upgrade, chunk)


def normalize_newlines(text: str) -> str:
    """Prepare Markdown text by normalizing newlines for better DOCX output.

    Transformations applied:
    - \\n before list/table  -> \\n\\n    (ensures block parsing)
    - \\n before # or >      -> bare      (can interrupt paragraphs natively)
    - other lone \\n         -> '  \\n'   (Markdown hard break)
    - \\n\\n                 -> unchanged (paragraph break)
    - 3+ \\n                 -> \\n\\n + EXTRA_NL sentinel
    """
    result: list[str] = []
    last_end = 0

    for match in FENCED_CODE_RE.finditer(text):
        before = text[last_end : match.start()]
        before = MULTI_NEWLINE_RE.sub(_expand_extra_newlines, before)
        before = _upgrade_block_starters(before)
        before = SINGLE_NEWLINE_RE.sub("  \n", before)
        result.append(before)
        result.append(match.group(0)) # code block untouched
        last_end = match.end()

    after = text[last_end:]
    after = MULTI_NEWLINE_RE.sub(_expand_extra_newlines, after)
    after = _upgrade_block_starters(after)
    after = SINGLE_NEWLINE_RE.sub("  \n", after)
    result.append(after)

    return "".join(result)
