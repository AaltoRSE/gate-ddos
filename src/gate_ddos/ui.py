import sys
import time
from pathlib import Path
import re
from typing import Any


try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
    )
    from rich.rule import Rule
    from rich.text import Text
except Exception:
    _RICH_COMPONENTS: dict[str, Any] = {}
else:
    _RICH_COMPONENTS = {
        "Console": Console,
        "Group": Group,
        "Live": Live,
        "Markdown": Markdown,
        "Panel": Panel,
        "Progress": Progress,
        "SpinnerColumn": SpinnerColumn,
        "TextColumn": TextColumn,
        "BarColumn": BarColumn,
        "MofNCompleteColumn": MofNCompleteColumn,
        "Rule": Rule,
        "Text": Text,
    }


class CliUI:
    """Small presentation layer for human-friendly CLI output."""

    def __init__(self, *, backend: str, model: str, enabled: bool = True):
        self.backend = backend
        self.model = model
        self.enabled = enabled
        self._progress = None
        self._task_id = None
        self._progress_total = 0
        self._progress_completed = 0
        self._progress_description = "Resolving sections"
        self._progress_suspended = False
        self._stream_open = False
        self._stream_live = None
        self._stream_title = "Draft"
        self._stream_answer_buffer = ""
        self._stream_thinking_buffer = ""
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
        """Render the run header and start section progress tracking."""
        if not self.enabled:
            return

        self._started_at = time.perf_counter()
        self._stats = self._new_stats()
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
            self._start_progress(total_sections)
            return

        self.note("No placeholders found. Writing output without any LLM generation.", style="yellow")

    def _start_progress(self, total_sections: int) -> None:
        """Create a progress bar for placeholder resolution."""
        if not self.enabled:
            return

        self._progress_total = total_sections
        self._progress_completed = 0
        self._progress_description = "Resolving sections"
        self._progress_suspended = False

        progress_cls = self._rich.get("Progress")
        if self._console is not None and progress_cls:
            self._create_progress(total_sections, completed=0, description=self._progress_description)
            return

        print(f"Sections: 0/{total_sections}", file=sys.stderr)

    def _create_progress(self, total_sections: int, *, completed: int, description: str) -> None:
        """Instantiate a Rich progress bar with preserved state."""
        progress_cls = self._rich.get("Progress")
        if self._console is None or progress_cls is None:
            return

        self._progress = progress_cls(
            self._rich["SpinnerColumn"](style="cyan"),
            self._rich["TextColumn"]("[bold cyan]{task.description}"),
            self._rich["BarColumn"](bar_width=28),
            self._rich["MofNCompleteColumn"](),
            console=self._console,
            transient=False,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(description, total=total_sections, completed=completed)

    def _stop_progress(self) -> None:
        """Stop the active progress display without discarding tracked state."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task_id = None

    def _clear_stream_state(self) -> None:
        """Reset any active stream buffers."""
        self._stream_answer_buffer = ""
        self._stream_thinking_buffer = ""
        self._stream_title = self._phase_title

    def _build_stream_renderable(self):
        """Build the live renderable for an active streamed response."""
        group_cls = self._rich.get("Group")
        markdown_cls = self._rich.get("Markdown")
        panel_cls = self._rich.get("Panel")
        text_cls = self._rich.get("Text")

        if panel_cls is None:
            return None

        blocks: list[Any] = []
        if self._stream_thinking_buffer.strip() and text_cls is not None:
            preview = self._tail_stream_lines(
                self._stream_thinking_buffer,
                max_lines=6,
            )
            blocks.append(panel_cls(text_cls(preview, style="yellow"), title="Thinking", border_style="yellow"))

        answer_text = self._stream_answer_buffer or "_Waiting for streamed content..._"
        answer_preview = self._tail_stream_lines(
            answer_text,
            max_lines=self._stream_answer_max_lines(),
        )
        if markdown_cls is not None:
            answer_renderable = markdown_cls(answer_preview)
        elif text_cls is not None:
            answer_renderable = text_cls(answer_preview)
        else:
            answer_renderable = answer_preview

        blocks.append(panel_cls(answer_renderable, title=self._stream_title, border_style="blue"))
        if group_cls is not None:
            return group_cls(*blocks)
        return blocks[-1]

    def _stream_answer_max_lines(self) -> int:
        """Estimate how many answer lines fit in the terminal during streaming."""
        if self._console is None:
            return 12

        reserved_lines = 7
        if self._stream_thinking_buffer.strip():
            reserved_lines += 9
        return max(6, self._console.size.height - reserved_lines)

    def _tail_stream_lines(self, text: str, *, max_lines: int) -> str:
        """Return the newest logical lines for compact live previews."""
        if not text:
            return ""

        lines = text.splitlines() or [text]
        if len(lines) <= max_lines:
            return "\n".join(lines)

        return "\n".join(lines[-max_lines:])

    def _ensure_stream_session(self) -> bool:
        """Start a live stream preview when Rich is available."""
        if not self.enabled:
            return False
        if self._stream_live is not None:
            return True

        self._suspend_progress()
        self._stream_open = True

        live_cls = self._rich.get("Live")
        if self._console is None or live_cls is None:
            return False

        renderable = self._build_stream_renderable()
        if renderable is None:
            return False

        self._stream_live = live_cls(renderable, console=self._console, transient=False, refresh_per_second=8)
        self._stream_live.start()
        return True

    def _update_stream_preview(self) -> None:
        """Refresh the active live markdown preview."""
        if self._stream_live is None:
            return
        renderable = self._build_stream_renderable()
        if renderable is not None:
            self._stream_live.update(renderable)

    def _suspend_progress(self) -> None:
        """Hide the live progress display while streaming inline output."""
        if self._progress is None or self._task_id is None:
            return
        self._stop_progress()
        self._progress_suspended = True

    def _resume_progress(self) -> None:
        """Restore the progress display after inline streaming completes."""
        if not self.enabled or not self._progress_suspended:
            return
        self._progress_suspended = False
        if self._progress_total <= 0 or self._progress_completed >= self._progress_total:
            return
        if self._console is not None and self._rich.get("Progress") is not None:
            self._create_progress(
                self._progress_total,
                completed=self._progress_completed,
                description=self._progress_description,
            )
            return
        print(f"Sections: {self._progress_completed}/{self._progress_total}", file=sys.stderr)

    def _update_progress(self, description: str | None = None, *, advance: int = 0) -> None:
        """Update the active progress task when present."""
        if description is not None:
            self._progress_description = description
        if advance:
            self._progress_completed += advance

        if (
            not self.enabled
            or self._progress_suspended
            or self._progress is None
            or self._task_id is None
        ):
            return
        update_kwargs = {"task_id": self._task_id, "advance": advance}
        if description is not None:
            update_kwargs["description"] = description
        self._progress.update(**update_kwargs)

    def section_key_only(self, section_key: str) -> None:
        """Report reuse of a key-only section."""
        self._active_section_started_at = None
        self._update_progress(f"Using stored section: {section_key}")

    def section_generating(self, section_key: str, prompt_preview: str, *, force: bool) -> None:
        """Report active section generation."""
        suffix = " (forced)" if force else ""
        self._active_section_started_at = time.perf_counter()
        self._update_progress(f"Generating section: {section_key}{suffix}")
        preview = self._preview_text(prompt_preview)
        self.note(f"[generate] {section_key}{suffix}: {preview}", style="cyan")

    def section_cached(self, section_key: str, source_label: str) -> None:
        """Report cache reuse for a prompted section."""
        self._active_section_started_at = None
        self._update_progress(f"Using cached {source_label}: {section_key}")
        self.note(f"[cache] {section_key} from {source_label}", style="blue")

    def section_done(self, section_key: str, source_label: str, text: str = "") -> None:
        """Advance the section progress bar and print a short completion line."""
        if not self.enabled:
            return
        self._update_progress(f"Completed section: {section_key}", advance=1)
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
        self.note(f"[{source_label}] {section_key}{suffix}", style=style)

    def phase(self, title: str, detail: str | None = None, *, stream_title: str | None = None) -> None:
        """Render a phase separator."""
        if not self.enabled:
            return

        self._phase_title = title
        self._stream_title = stream_title or title

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
        if self._ensure_stream_session():
            self._stream_thinking_buffer += text
            self._update_stream_preview()
            return
        self._write(text, style="yellow")

    def answer(self, text: str) -> None:
        """Stream assistant answer text."""
        if self._ensure_stream_session():
            self._stream_answer_buffer += text
            self._update_stream_preview()
            return
        self._write(text)

    def _write(self, text: str, *, style: str | None = None) -> None:
        """Write inline console content without forcing a newline."""
        if not self.enabled or not text:
            return

        text_cls = self._rich.get("Text")
        if self._console is not None and text_cls:
            if not self._stream_open:
                self._suspend_progress()
                self._stream_open = True
            rendered = text_cls(text, style=style) if style else text_cls(text)
            self._console.print(rendered, end="")
            self._console.file.flush()
            return
        print(text, end="", file=sys.stderr, flush=True)

    def stream_done(self) -> None:
        """Terminate the current streamed line."""
        if not self.enabled:
            return
        if self._stream_live is not None:
            self._update_stream_preview()
            self._stream_live.stop()
            self._stream_live = None
            self._stream_open = False
            self._clear_stream_state()
            self._resume_progress()
            return
        if self._console is not None:
            if self._stream_open:
                self._console.print()
                self._console.file.flush()
                self._stream_open = False
                self._clear_stream_state()
                self._resume_progress()
                return
            self._console.print()
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
            self._console.print(panel_cls(markdown_cls(content), title=title, border_style="blue"))
            return
        print(content, file=sys.stderr)

    def close(self) -> None:
        """Stop any active progress display."""
        if self._stream_live is not None:
            self._stream_live.stop()
            self._stream_live = None
        self._stream_open = False
        self._progress_suspended = False
        self._clear_stream_state()
        self._stop_progress()

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
