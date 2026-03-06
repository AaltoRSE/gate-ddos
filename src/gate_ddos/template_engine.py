import re
import warnings
from typing import Callable

from .models import TemplateSyntax
from .section_store import SectionStore


def build_placeholder_pattern(syntax: TemplateSyntax) -> re.Pattern:
    """Compile a regex that matches template placeholders based on the provided syntax."""
    open_esc = re.escape(syntax.open_delim)
    close_esc = re.escape(syntax.close_delim)
    open_boundary = re.escape(syntax.open_delim[-1])
    close_boundary = re.escape(syntax.close_delim[0])
    return re.compile(rf"(?<!{open_boundary}){open_esc}\s+(.*?)\s+{close_esc}(?!{close_boundary})", re.DOTALL)


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


def build_replacer(
    system_prompt: str,
    model: str,
    syntax: TemplateSyntax,
    store: SectionStore,
    generate: Callable[[str, str, str], str],
    force: bool = False,
) -> Callable[[str], str]:
    """Return a function that replaces all template placeholders in a string."""
    pattern = build_placeholder_pattern(syntax)

    def _resolve_key_only(section_key: str) -> str:
        """Handle a key-only placeholder (no prompt)."""
        output = store.resolve(section_key, None, None)
        if output:
            print(f"\n=== Using key-only section {section_key} from JSON/cache ===\n")
        return output

    def _resolve_prompted(section_key: str, user_prompt: str) -> str:
        """Handle a placeholder that carries a prompt."""
        was_generated = False

        def _do_generate(prompt: str) -> str:
            nonlocal was_generated
            was_generated = True
            print(f"\n=== Generating section {section_key} ===\n")
            return generate(system_prompt, prompt, model).strip()

        output = store.resolve(section_key, user_prompt, _do_generate, force_generate=force)

        if not was_generated:
            rec_source = store.records[section_key].source
            label = "JSON file" if rec_source == "json" else "LLM cache"
            print(f"\n=== Using cached section {section_key} from {label} ===\n")

        return output

    def _on_match(match: re.Match) -> str:
        try:
            section_key, user_prompt = parse_placeholder(match.group(1), syntax)
        except ValueError as exc:
            warnings.warn(f"Skipping invalid placeholder: {exc}", stacklevel=2)
            return match.group(0)

        if user_prompt is None:
            return _resolve_key_only(section_key)

        try:
            return _resolve_prompted(section_key, user_prompt)
        except Exception as exc:
            warnings.warn(f"Error processing section '{section_key}': {exc}", stacklevel=2)
            return match.group(0)

    def replace_text(text: str) -> str:
        return pattern.sub(_on_match, text) if text else text

    return replace_text
