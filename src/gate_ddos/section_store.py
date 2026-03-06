from datetime import datetime, timezone
from typing import Callable

from .constants import JSON_VERSION
from .models import SectionRecord


class SectionStore:
    """Holds section records and resolves placeholders via cache or generation."""

    def __init__(self, initial_records: dict[str, SectionRecord] | None = None):
        self.records: dict[str, SectionRecord] = initial_records or {}

    def resolve(
        self,
        section_key: str,
        prompt: str | None,
        generator: Callable[[str], str] | None,
        force_generate: bool = False,
    ) -> str:
        """Resolve a section key to its output, using cache or generator as needed."""
        existing = self.records.get(section_key)

        if prompt is None:
            return existing.output if existing else ""

        if existing and existing.prompt and existing.prompt != prompt:
            raise ValueError(f"Section key '{section_key}' is reused with different prompts")

        if existing and not existing.prompt:
            existing.prompt = prompt

        if existing and not force_generate:
            return existing.output

        if generator is None:
            raise ValueError(f"Section '{section_key}' has no cached output and no generator is available")

        output = generator(prompt)
        if output is None:
            raise RuntimeError(f"Generator for section '{section_key}' returned None instead of a string")

        self.records[section_key] = SectionRecord(prompt=prompt, output=str(output), source="llm")
        return self.records[section_key].output

    def to_json_payload(self, model: str) -> dict:
        """Serialize all records into a JSON-ready dict."""
        ordered = dict(sorted(self.records.items()))
        return {
            "version": JSON_VERSION,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "sections": {
                key: {"prompt": rec.prompt, "output": rec.output, "source": rec.source}
                for key, rec in ordered.items()
            },
        }
