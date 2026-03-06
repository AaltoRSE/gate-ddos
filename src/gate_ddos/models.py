from dataclasses import dataclass
from typing import Literal


@dataclass
class SectionRecord:
    """A single generated or cached section with its prompt and output."""

    prompt: str
    output: str
    source: Literal["json", "llm"]


@dataclass(frozen=True)
class TemplateSyntax:
    """Delimiter configuration for template placeholders."""

    open_delim: str = "{{"
    close_delim: str = "}}"
    separator: str = "||"

    def expected_format(self) -> str:
        """Return a human-readable example of the expected placeholder format."""
        return (
            f"{self.open_delim} SECTION_KEY {self.separator} Prompt text "
            f"{self.close_delim}"
        )
