import json
from pathlib import Path

from .utils import read_text
from .models import SectionRecord
from .section_store import SectionStore


def _parse_section_value(key: str, value) -> SectionRecord:
    """Convert a raw JSON value into a SectionRecord."""
    if isinstance(value, str):
        return SectionRecord(prompt="", output=value, source="json")

    if isinstance(value, dict):
        return SectionRecord(
            prompt=str(value.get("prompt", "")).strip(),
            output=str(value.get("output", "")).strip(),
            source="json",
        )

    raise ValueError(f"Invalid section '{key}' format in JSON")


def records_from_payload(payload: dict) -> dict[str, SectionRecord]:
    """Extract section records from a JSON payload."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON format: top-level value must be an object")

    if "sections" in payload:
        sections = payload["sections"]
        if not isinstance(sections, dict):
            raise ValueError("Invalid JSON format: 'sections' must be an object")
        payload = sections

    return {key: _parse_section_value(key, val) for key, val in payload.items()}


def read_json_store(path: str | None) -> SectionStore:
    """Load a SectionStore from a JSON file or return an empty store."""
    if not path:
        return SectionStore()

    source = Path(path)
    if not source.exists():
        return SectionStore()

    text = read_text(source, "JSON data")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in '{source}' at line {exc.lineno}, col {exc.colno}: {exc.msg}") from exc

    return SectionStore(records_from_payload(payload))


def write_json_store(path: str | None, store: SectionStore, model: str) -> None:
    """Persist the store to a JSON file. No-op when path is falsy."""
    if not path:
        return

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = store.to_json_payload(model)
    # Write to a .tmp first so a crash never leaves a truncated file.
    tmp = target.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
