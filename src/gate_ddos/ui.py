import io
import sys
import time
from pathlib import Path
import re
from typing import Any


try:
    from rich.console import Console, Group
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text
except Exception:
    _RICH_COMPONENTS: dict[str, Any] = {}
else:
    _RICH_COMPONENTS = {
        "Console": Console,
        "Group": Group,
        "Markdown": Markdown,
        "Panel": Panel,
        "Rule": Rule,
        "Text": Text,
    }


class CliUI:
    """Small presentation layer for human-friendly CLI output."""

    def __init__(self, *, backend: str, model: str, enabled: bool = True):
        self.backend = backend
        self.model = model
        self.enabled = enabled
        self._total_sections = 0
        self._completed_sections = 0
        self._current_section_key: str | None = None
        self._stream_open = False
        self._stream_frame_open = False
        self._stream_title = "Draft"
        self._stream_answer_buffer = ""
        self._stream_rendered_length = 0
        self._phase_title = "Run"
        self._started_at = time.perf_counter()
        self._active_section_started_at: float | None = None
        self._run_config: dict[str, str] = {}
        self._stats = self._new_stats()
        self._rich = _RICH_COMPONENTS if enabled else {}
        console_cls = self._rich.get("Console")
        self._console = console_cls(stderr=True, soft_wrap=False, highlight=False) if console_cls else None

    def _new_stats(self) -> dict[str, int]:
        """Create a fresh stats object for the current run."""
        return {
            "generated": 0,
            "cached": 0,
            "stored": 0,
            "empty": 0,
            "skipped": 0,
            "warnings": 0,
            "retries": 0,
        }

    def configure_run(
        self,
        *,
        api_base: str,
        cache_path: str | Path | None,
        thinking: bool | None = None,
        stream: bool = True,
        force: bool,
    ) -> None:
        """Store run configuration so the header and summary can show it."""
        cache_label = Path(cache_path).name if cache_path else "off"

        self._run_config = {
            "API": api_base,
            "Cache": cache_label,
            "Thinking": "on" if thinking else "off",
            "Streaming": "on" if stream else "off",
            "Force": "on" if force else "off",
        }

    def _summary_lines(self, template: Path, output: Path, total_sections: int) -> list[Any]:
        """Build header summary lines for the current run."""
        text_cls = self._rich.get("Text")
        if text_cls is None:
            return []

        entries = [
            ("Template", template.name),
            ("Output", output.name),
            ("Backend", self.backend),
            ("Model", self.model),
            ("Sections", str(total_sections)),
        ]
        for key in ("API", "Cache", "Thinking", "Streaming", "Force"):
            value = self._run_config.get(key)
            if value is not None:
                entries.append((key, value))

        label_width = max(len(label) for label, _ in entries)
        return [
            text_cls(f"{label:<{label_width}} : {value}")
            for label, value in entries
        ]

    def _stats_summary_text(self) -> str:
        """Return a compact stats summary line."""
        return (
            f"generated={self._stats['generated']} | cached={self._stats['cached']} | "
            f"stored={self._stats['stored']} | empty={self._stats['empty']} | "
            f"skipped={self._stats['skipped']} | warnings={self._stats['warnings']} | "
            f"retries={self._stats['retries']}"
        )

    def _preview_text(self, text: str, *, limit: int = 88) -> str:
        """Collapse text into a short single-line preview."""
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    @classmethod
    def _section_metrics_text(
        cls,
        text: str,
        *,
        elapsed_seconds: float | None = None,
    ) -> str:
        """Format size metrics for a generated or cached section."""
        char_count = len(text)
        if char_count <= 0:
            return ""

        word_count = len(re.findall(r"\b\w+\b", text))
        parts = [f"{char_count} chars", f"{word_count} words"]
        if elapsed_seconds is not None:
            parts.append(cls._format_elapsed(elapsed_seconds))
        return f" ({', '.join(parts)})"

    @staticmethod
    def _format_elapsed(elapsed_seconds: float) -> str:
        """Render elapsed time using mixed units for longer runs."""
        if elapsed_seconds < 60:
            return f"{elapsed_seconds:.1f}s"

        remaining_seconds = int(round(elapsed_seconds))
        days, remaining_seconds = divmod(remaining_seconds, 86400)
        hours, remaining_seconds = divmod(remaining_seconds, 3600)
        minutes, seconds = divmod(remaining_seconds, 60)

        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    def start_template(self, template_path: str | Path, output_path: str | Path, total_sections: int) -> None:
        """Render the run header and initialize section tracking."""
        if not self.enabled:
            return

        self._started_at = time.perf_counter()
        self._stats = self._new_stats()
        self._total_sections = total_sections
        self._completed_sections = 0
        self._current_section_key = None
        self._stream_open = False
        template = Path(template_path)
        output = Path(output_path)
        group_cls = self._rich.get("Group")
        panel_cls = self._rich.get("Panel")
        text_cls = self._rich.get("Text")
        if self._console is not None and group_cls and panel_cls and text_cls:
            summary = group_cls(*self._summary_lines(template, output, total_sections))
            self._console.print(panel_cls(summary, title="gate-ddos", border_style="cyan"))
        else:
            print(
                f"gate-ddos | template={template.name} output={output.name} backend={self.backend} "
                f"model={self.model} sections={total_sections}",
                file=sys.stderr,
            )

        if total_sections > 0:
            self.note(f"Loaded template and found {total_sections} placeholder(s).", style="cyan")
            return

        self.note("No placeholders found. Writing output without any LLM generation.", style="yellow")

    def _clear_stream_state(self) -> None:
        """Reset stream state for the next section."""
        self._stream_open = False
        self._stream_frame_open = False
        self._stream_answer_buffer = ""
        self._stream_rendered_length = 0
        self._stream_title = self._phase_title

    def _markdown_stream_enabled(self) -> bool:
        """Return True when the console can render incremental markdown."""
        return self._console is not None and self._rich.get("Markdown") is not None

    def _ensure_stream_header(self) -> None:
        """Print the per-section stream heading once."""
        if self._stream_open:
            return
        if self._markdown_stream_enabled():
            self._open_stream_frame()
            return
        self.note(f"{self._stream_title} | {self._section_label()}", style="magenta")
        self._stream_open = True

    def _stream_frame_width(self) -> int:
        """Return the width used for the static draft frame."""
        if self._console is None:
            return 80
        return max(40, min(self._console.size.width, 120))

    def _stream_frame_content_width(self) -> int:
        """Return the content width inside the draft frame."""
        return self._stream_frame_width() - 4

    def _stream_border(self, title: str | None = None):
        """Build a single-line smooth border for the draft frame."""
        width = self._stream_frame_width()
        if width < 4:
            width = 4
        text_cls = self._rich.get("Text")
        inner = max(0, width - 2)

        if not title:
            line = "╰" + ("─" * inner) + "╯"
            return text_cls(line, style="blue") if text_cls is not None else line

        label = f" {title} "
        if len(label) >= inner:
            trimmed = label[:inner]
            line = "╭" + trimmed + "╮"
            return text_cls(line, style="blue") if text_cls is not None else line

        remaining = inner - len(label)
        left = remaining // 2
        right = remaining - left
        if text_cls is None:
            return "╭" + ("─" * left) + label + ("─" * right) + "╮"

        border = text_cls()
        border.append("╭", style="blue")
        border.append("─" * left, style="blue")
        border.append(label, style="bold cyan")
        border.append("─" * right, style="blue")
        border.append("╮", style="blue")
        return border

    def _stream_frame_line(self, line: str = ""):
        """Build one line inside the static draft frame."""
        content_width = self._stream_frame_content_width()
        if len(line) > content_width:
            line = line[:content_width]
        text_cls = self._rich.get("Text")
        padded = line.ljust(content_width)
        if text_cls is None:
            return f"│ {padded} │"

        framed = text_cls()
        framed.append("│ ", style="blue")
        framed.append(padded)
        framed.append(" │", style="blue")
        return framed

    def _print_stream_frame_line(self, line: str = "") -> None:
        """Print one line inside the static draft frame."""
        print_line = self._stream_frame_line(line)
        if self._console is not None:
            self._console.print(print_line)
            self._console.file.flush()
            return
        print(print_line, file=sys.stderr)

    def _open_stream_frame(self) -> None:
        """Open the static draft frame once for the current stream."""
        if self._stream_frame_open:
            return
        title = f"{self._stream_title} | {self._section_label()}"
        border = self._stream_border(title)
        if self._console is not None:
            self._console.print(border)
            self._console.file.flush()
        else:
            print(border, file=sys.stderr)
        self._stream_open = True
        self._stream_frame_open = True

    def _close_stream_frame(self) -> None:
        """Close the static draft frame after streaming completes."""
        if not self._stream_frame_open:
            return
        border = self._stream_border()
        if self._console is not None:
            self._console.print(border)
            self._console.file.flush()
        else:
            print(border, file=sys.stderr)
        self._stream_frame_open = False

    @staticmethod
    def _balanced_fences(text: str) -> bool:
        """Return True when common fenced-code markers are balanced."""
        return text.count("```") % 2 == 0 and text.count("~~~") % 2 == 0

    @classmethod
    def _markdown_flush_boundary(cls, text: str) -> int:
        """Return a safe incremental flush point for streamed markdown."""
        boundary = text.rfind("\n") + 1
        while boundary > 0:
            if cls._balanced_fences(text[:boundary]):
                return boundary
            boundary = text.rfind("\n", 0, max(0, boundary - 1)) + 1
        return 0

    def _render_markdown_chunk(self, content: str) -> None:
        """Render one markdown chunk without using a live-updating view."""
        markdown_cls = self._rich.get("Markdown")
        if self._console is None or markdown_cls is None or not content.strip():
            return

        capture = io.StringIO()
        render_console = self._rich["Console"](
            file=capture,
            width=self._stream_frame_content_width(),
            soft_wrap=False,
            highlight=False,
            color_system=None,
        )
        render_console.print(markdown_cls(content), end="")
        rendered = capture.getvalue().rstrip("\n")
        lines = rendered.splitlines() if rendered else [""]
        for line in lines:
            self._print_stream_frame_line(line)

    def _flush_stream_markdown(self, *, final: bool = False, content: str | None = None) -> None:
        """Render newly completed markdown content for the active stream."""
        if not self._markdown_stream_enabled():
            return

        if final and content is not None:
            self._stream_answer_buffer = content

        pending = self._stream_answer_buffer[self._stream_rendered_length :]
        if not pending:
            return

        boundary = len(pending) if final else self._markdown_flush_boundary(pending)
        if boundary <= 0:
            return

        chunk = pending[:boundary]
        self._render_markdown_chunk(chunk)
        self._stream_rendered_length += boundary

    def _section_position(self) -> str:
        """Return the current section position label."""
        if self._total_sections <= 0:
            return "[0/0]"

        current = min(self._completed_sections + 1, self._total_sections)
        return f"[{current}/{self._total_sections}]"

    def _section_label(self, section_key: str | None = None) -> str:
        """Return a compact label for the active section."""
        key = section_key or self._current_section_key or "section"
        return f"{self._section_position()} {key}"

    def _set_current_section(self, section_key: str) -> None:
        """Track which section is currently being processed."""
        self._current_section_key = section_key

    def section_key_only(self, section_key: str) -> None:
        """Report reuse of a key-only section."""
        self._active_section_started_at = None
        self._set_current_section(section_key)
        self.note(f"{self._section_label(section_key)} | using stored section", style="blue")

    def section_generating(self, section_key: str, prompt_preview: str, *, force: bool) -> None:
        """Report active section generation."""
        suffix = " (forced)" if force else ""
        self._active_section_started_at = time.perf_counter()
        self._set_current_section(section_key)
        preview = self._preview_text(prompt_preview)
        self.note(
            f"{self._section_label(section_key)} | generating{suffix} | prompt: {preview}",
            style="cyan",
        )

    def section_cached(self, section_key: str, source_label: str) -> None:
        """Report cache reuse for a prompted section."""
        self._active_section_started_at = None
        self._set_current_section(section_key)
        self.note(f"{self._section_label(section_key)} | using {source_label}", style="blue")

    def section_done(self, section_key: str, source_label: str, text: str = "") -> None:
        """Advance the section progress bar and print a short completion line."""
        if not self.enabled:
            return
        style = "green"
        if source_label in {"JSON file", "LLM cache", "stored"}:
            self._stats["cached"] += 1 if source_label in {"JSON file", "LLM cache"} else 0
            self._stats["stored"] += 1 if source_label == "stored" else 0
            style = "blue" if source_label in {"JSON file", "LLM cache"} else "cyan"
        elif source_label == "generated":
            self._stats["generated"] += 1
        elif source_label == "empty":
            self._stats["empty"] += 1
            style = "yellow"
        elif source_label == "skipped":
            self._stats["skipped"] += 1
            style = "yellow"
        elapsed_seconds = None
        if source_label == "generated" and self._active_section_started_at is not None:
            elapsed_seconds = max(0.0, time.perf_counter() - self._active_section_started_at)
        self._active_section_started_at = None
        suffix = self._section_metrics_text(text, elapsed_seconds=elapsed_seconds)
        self.note(f"{self._section_label(section_key)} | {source_label}{suffix}", style=style)
        if self._completed_sections < self._total_sections:
            self._completed_sections += 1
        self._current_section_key = None

    def phase(
        self,
        title: str,
        detail: str | None = None,
        *,
        stream_title: str | None = None,
        render: bool = True,
    ) -> None:
        """Render a phase separator."""
        if not self.enabled:
            return

        self._phase_title = title
        self._stream_title = stream_title or title

        if not render:
            return

        rule_cls = self._rich.get("Rule")
        if self._console is not None and rule_cls:
            self._console.print(rule_cls(title, style="blue"))
        else:
            print(f"--- {title} ---", file=sys.stderr)

        if detail:
            self.note(detail, style="cyan")

    def note(self, message: str, *, style: str = "cyan") -> None:
        """Print a styled informational line."""
        if not self.enabled:
            return

        text_cls = self._rich.get("Text")
        if self._console is not None and text_cls:
            self._console.print(text_cls(message, style=style))
            return
        print(message, file=sys.stderr)

    def warning(self, message: str) -> None:
        """Print a warning line."""
        self._stats["warnings"] += 1
        self.note(message, style="yellow")

    def retry(
        self,
        kind: str,
        phase: str,
        attempt: int,
        max_retries: int,
        delay_seconds: int | float,
        exc: Exception,
    ) -> None:
        """Report a retryable failure."""
        self._stats["retries"] += 1
        self.warning(
            f"{kind} in {phase} (attempt {attempt}/{max_retries}): {exc}. Retrying in {delay_seconds}s."
        )

    def thinking(self, text: str) -> None:
        """Stream model reasoning text when enabled."""
        self._write(text, style="yellow")

    def answer(self, text: str) -> None:
        """Stream assistant answer text."""
        self._stream_answer_buffer += text
        if self._markdown_stream_enabled():
            self._ensure_stream_header()
            self._flush_stream_markdown()
            return
        self._write(text)

    def _write(self, text: str, *, style: str | None = None) -> None:
        """Write inline console content without forcing a newline."""
        if not self.enabled or not text:
            return

        text_cls = self._rich.get("Text")
        self._ensure_stream_header()

        if self._console is not None and text_cls:
            rendered = text_cls(text, style=style) if style else text_cls(text)
            self._console.print(rendered, end="")
            self._console.file.flush()
            return
        print(text, end="", file=sys.stderr, flush=True)

    def stream_done(self, content: str | None = None) -> None:
        """Terminate the current streamed line."""
        if not self.enabled:
            return

        final_content = content if content is not None else self._stream_answer_buffer
        if self._markdown_stream_enabled():
            if final_content:
                self._ensure_stream_header()
                self._flush_stream_markdown(final=True, content=final_content)
            self._close_stream_frame()
            self._clear_stream_state()
            return

        if self._console is not None:
            if self._stream_open:
                self._console.print()
                self._console.file.flush()
            else:
                self._console.print()
            self.render_markdown(self._stream_title, final_content)
            self._clear_stream_state()
            return
        print(file=sys.stderr)
        self._clear_stream_state()

    def render_markdown(self, title: str, content: str) -> None:
        """Render a completed response as markdown when streaming is disabled."""
        if not self.enabled or not content:
            return

        markdown_cls = self._rich.get("Markdown")
        panel_cls = self._rich.get("Panel")
        if self._console is not None and markdown_cls and panel_cls:
            self._console.print(panel_cls(markdown_cls(content), title=f"{title} Markdown", border_style="blue"))
            return
        print(content, file=sys.stderr)

    def close(self) -> None:
        """Stop any active progress display."""
        self._clear_stream_state()

    def complete(self, output_path: str | Path) -> None:
        """Stop progress tracking and render the final success message."""
        if not self.enabled:
            return
        self.close()

        output = Path(output_path)
        elapsed = time.perf_counter() - self._started_at
        elapsed_text = self._format_elapsed(elapsed)
        panel_cls = self._rich.get("Panel")
        group_cls = self._rich.get("Group")
        text_cls = self._rich.get("Text")
        if self._console is not None and panel_cls and text_cls and group_cls:
            summary = group_cls(
                text_cls(f"Saved: {output}"),
                text_cls(f"Elapsed: {elapsed_text}"),
                text_cls(self._stats_summary_text()),
            )
            self._console.print(panel_cls(summary, title="Complete", border_style="green"))
            return
        print(f"Saved: {output}", file=sys.stderr)
        print(f"Elapsed: {elapsed_text}", file=sys.stderr)
        print(self._stats_summary_text(), file=sys.stderr)
