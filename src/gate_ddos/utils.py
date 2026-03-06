from pathlib import Path

TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252")


def read_text(path: str | Path, label: str) -> str:
    """Read a text file with multiple encoding fallbacks and return its content as a string."""
    source = Path(path)

    if not source.exists():
        raise FileNotFoundError(f"{label} file not found: {source}")
    if source.suffix.lower() == ".docx":
        raise ValueError(f"{label} must be a text file, not .docx: {source}.")

    content = source.read_bytes()
    if b"\x00" in content:
        raise ValueError(f"{label} appears to be a binary file: {source}. Use a text file like .md or .txt.")

    for encoding in TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise ValueError(f"Could not decode '{source}'. Supported encodings: {', '.join(TEXT_ENCODINGS)}.")


def ensure_docx_path(path: str | Path, label: str) -> Path:
    """Validate that path points to an existing .docx file and return it."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"{label} file not found: {source}")
    if source.suffix.lower() != ".docx":
        raise ValueError(f"{label} must be a .docx file: {source}")
    return source


def default_output_path(template_path: str | Path) -> str:
    """Generate a default output path by appending '-new' to the template filename."""
    template = Path(template_path)
    return str(template.with_name(f"{template.stem}-new.docx"))
