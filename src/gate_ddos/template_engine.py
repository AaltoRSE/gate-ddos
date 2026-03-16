import re
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from .models import TemplateSyntax
from .section_store import SectionStore
from .ui import CliUI


@lru_cache(maxsize=None)
def build_placeholder_pattern(syntax: TemplateSyntax) -> re.Pattern:
    """Compile a regex that matches template placeholders based on the provided syntax."""
    open_esc = re.escape(syntax.open_delim)
    close_esc = re.escape(syntax.close_delim)
    open_boundary = re.escape(syntax.open_delim[-1])
    close_boundary = re.escape(syntax.close_delim[0])
    return re.compile(rf"(?<!{open_boundary}){open_esc}\s+(.*?)\s+{close_esc}(?!{close_boundary})", re.DOTALL)


def count_placeholders(text: str, syntax: TemplateSyntax) -> int:
    """Count placeholders in a block of template text."""
    if not text:
        return 0
    return len(build_placeholder_pattern(syntax).findall(text))


def parse_placeholder(body: str, syntax: TemplateSyntax) -> tuple[str, str | None]:
    """Split a placeholder body into ``(section_key, prompt_or_None)``."""
    key, separator, prompt = body.partition(syntax.separator)

    if not separator:
        section_key = body.strip()
        if not section_key:
            raise ValueError(f"Invalid template placeholder. Use {syntax.expected_format()} or {syntax.open_delim} KEY {syntax.close_delim}.")
        return section_key, None

    section_key = key.strip()
    user_prompt = prompt.strip()

    if not section_key:
        raise ValueError("Template placeholder has empty section key")
    if not user_prompt:
        raise ValueError(f"Template placeholder '{section_key}' has empty prompt")

    return section_key, user_prompt


@dataclass(frozen=True)
class ResolvedSection:
    key: str
    prompt: str
    output: str


class TemplateEngine:
    """Resolves template placeholders by coordinating store lookups and LLM generation."""

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
        self.system_prompt = system_prompt
        self.syntax = syntax
        self.store = store
        self._generate = generate
        self.force = force
        self.ui = ui
        self._pattern = build_placeholder_pattern(syntax)
        self._seen_prompts: dict[str, str] = {}
        self._resolved_refs: list[tuple[str, str]] = []
        self._recorded_refs: set[tuple[str, str]] = set()

    def replace(self, text: str) -> str:
        """Replace all template placeholders in *text* and return the result."""
        if not text:
            return text
        return self._pattern.sub(self._resolve_match, text)

    def count(self, text: str) -> int:
        """Count placeholders in *text*."""
        return count_placeholders(text, self.syntax)

    def resolved_sections(self) -> list[ResolvedSection]:
        """Return prompted sections resolved during this run in document order."""
        sections: list[ResolvedSection] = []
        for key, prompt in self._resolved_refs:
            record = self.store.records.get(key)
            if record is None or record.prompt != prompt or not record.output.strip():
                continue
            sections.append(ResolvedSection(key=key, prompt=prompt, output=record.output))
        return sections

    def _resolve_match(self, match: re.Match) -> str:
        raw_body = match.group(1).strip()
        try:
            section_key, user_prompt = parse_placeholder(match.group(1), self.syntax)
        except ValueError as exc:
            return self._warn_and_keep(raw_body or "invalid", match.group(0), f"Skipping invalid placeholder: {exc}")

        if user_prompt is None:
            return self._resolve_key_only(section_key)

        previous_prompt = self._seen_prompts.setdefault(section_key, user_prompt)
        if previous_prompt != user_prompt:
            return self._warn_and_keep(
                section_key,
                match.group(0),
                f"Error processing section '{section_key}': section key is used with multiple different prompts in the same document",
            )

        try:
            return self._resolve_prompted(section_key, user_prompt)
        except Exception as exc:
            return self._warn_and_keep(section_key, match.group(0), f"Error processing section '{section_key}': {exc}")

    def _resolve_key_only(self, section_key: str) -> str:
        output = self.store.resolve(section_key, None, None)
        if self.ui is not None:
            self.ui.section_key_only(section_key)
            self.ui.section_done(section_key, "stored" if output else "empty", output)
        return output

    def _resolve_prompted(self, section_key: str, user_prompt: str) -> str:
        was_generated = False

        def do_generate(prompt: str) -> str:
            nonlocal was_generated
            was_generated = True
            if self.ui is not None:
                self.ui.section_generating(section_key, prompt, force=self.force)
            return self._generate(self.system_prompt, user_prompt).strip()

        output = self.store.resolve(section_key, user_prompt, do_generate, force_generate=self.force)
        self._record_resolved_output(section_key, user_prompt)
        if self.ui is not None:
            if was_generated:
                self.ui.section_done(section_key, "generated", output)
            else:
                rec_source = self.store.records[section_key].source
                label = "JSON file" if rec_source == "json" else "LLM cache"
                self.ui.section_cached(section_key, label)
                self.ui.section_done(section_key, label, output)
        return output

    def _record_resolved_output(self, section_key: str, user_prompt: str) -> None:
        ref = (section_key, user_prompt)
        if ref in self._recorded_refs:
            return
        self._recorded_refs.add(ref)
        self._resolved_refs.append(ref)

    def _warn_and_keep(self, section_key: str, original: str, message: str) -> str:
        warnings.warn(message, stacklevel=2)
        if self.ui is not None:
            self.ui.section_done(section_key, "skipped")
        return original
