import io
import sys
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch
from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.ui import CliUI


class CliUiTests(unittest.TestCase):
    def test_section_generating_combines_prompt_into_status_line(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = None

        stderr = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = stderr
        try:
            ui.start_template("template.md", "output.md", 1)
            ui.section_generating("SUMMARY", "one sentence", force=False)
        finally:
            sys.stderr = original_stderr

        output = stderr.getvalue()
        self.assertIn("[1/1] SUMMARY | generating | prompt: one sentence", output)
        self.assertNotIn("Prompt: one sentence", output)

    def test_section_done_includes_chars_words_and_generation_time(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = None

        stderr = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = stderr
        try:
            with patch("gate_ddos.ui.time.perf_counter", side_effect=[100.0, 101.6]):
                ui.section_generating("SUMMARY", "one sentence", force=False)
                ui.section_done("SUMMARY", "generated", "One two three four five")
        finally:
            sys.stderr = original_stderr

        output = stderr.getvalue()
        self.assertIn("generated", output)
        self.assertIn("chars", output)
        self.assertIn("5 words", output)
        self.assertIn("1.6s", output)

    def test_stream_output_prints_section_heading_once(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(file=io.StringIO(), width=60, soft_wrap=False, force_terminal=False, color_system=None)
        ui.start_template("template.md", "output.md", 1)
        ui.section_generating("SUMMARY", "one sentence", force=False)
        ui.phase("Draft")

        ui.answer("Hello")
        ui.answer(" world")
        ui.stream_done()

        console_file = cast(io.StringIO, ui._console.file)
        self.assertIsInstance(console_file, io.StringIO)
        output = console_file.getvalue()

        self.assertNotIn(" Section ", output)
        self.assertIn("Draft | [1/1] SUMMARY", output)
        self.assertEqual(output.count("Draft | [1/1] SUMMARY"), 1)
        self.assertIn("Hello world", output)
        self.assertEqual(output.count("Hello world"), 1)
        self.assertIn("╭", output)
        self.assertIn("╰", output)
        self.assertIn("│ Hello world", output)

    def test_stream_done_renders_final_markdown_once(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(file=io.StringIO(), width=60, soft_wrap=False, force_terminal=False, color_system=None)
        ui.start_template("template.md", "output.md", 1)
        ui.section_generating("SUMMARY", "one sentence", force=False)
        ui.phase("Draft")

        ui.answer("# Title\n\n- one\n- two")
        ui.stream_done("# Title\n\n- one\n- two")

        console_file = cast(io.StringIO, ui._console.file)
        output = console_file.getvalue()

        self.assertNotIn("Draft Markdown", output)
        self.assertIn("Title", output)
        self.assertIn("one", output)
        self.assertIn("two", output)
        self.assertNotIn("# Title", output)
        self.assertNotIn("- one", output)
        self.assertIn("╭", output)
        self.assertIn("╰", output)
        self.assertIn("│", output)

    def test_streamed_markdown_preserves_bold_styling(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(
            file=io.StringIO(),
            width=60,
            soft_wrap=False,
            force_terminal=True,
            color_system="truecolor",
            legacy_windows=False,
        )
        ui.start_template("template.md", "output.md", 1)
        ui.section_generating("SUMMARY", "one sentence", force=False)
        ui.phase("Draft")

        ui.answer("**bold**")
        ui.stream_done("**bold**")

        console_file = cast(io.StringIO, ui._console.file)
        output = console_file.getvalue()

        self.assertNotIn("**bold**", output)
        self.assertIn("\x1b[1m", output)
        self.assertIn("bold", output)

    def test_streamed_markdown_renders_tables(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(
            file=io.StringIO(),
            width=60,
            soft_wrap=False,
            force_terminal=False,
            color_system=None,
        )
        ui.start_template("template.md", "output.md", 1)
        ui.section_generating("SUMMARY", "one sentence", force=False)
        ui.phase("Draft")

        table = "| A | B |\n|---|---|\n| 1 | 2 |"
        ui.answer(table)
        ui.stream_done(table)

        console_file = cast(io.StringIO, ui._console.file)
        output = console_file.getvalue()

        self.assertNotIn("| A | B |", output)
        self.assertIn("A", output)
        self.assertIn("B", output)
        self.assertIn("1", output)
        self.assertIn("2", output)
        self.assertIn("─", output)

    def test_phase_can_use_distinct_stream_panel_title(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)

        ui.phase("Generating response", stream_title="Draft")

        self.assertEqual(ui._phase_title, "Generating response")
        self.assertEqual(ui._stream_title, "Draft")

    def test_stream_session_keeps_custom_stream_panel_title(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(file=io.StringIO(), width=60, soft_wrap=False, force_terminal=False, color_system=None)

        ui.start_template("template.md", "output.md", 1)
        ui.section_generating("SUMMARY", "one sentence", force=False)
        ui.phase("Generating response", stream_title="Draft")
        ui.answer("Hello")

        self.assertEqual(ui._phase_title, "Generating response")
        self.assertEqual(ui._stream_title, "Draft")

    def test_stream_done_resets_stream_state(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(file=io.StringIO(), width=60, soft_wrap=False, force_terminal=False, color_system=None)

        ui.start_template("template.md", "output.md", 1)
        ui.section_generating("SUMMARY", "one sentence", force=False)
        ui.phase("Generating response", stream_title="Draft")
        ui.answer("Hello")
        ui.stream_done()

        self.assertFalse(ui._stream_open)
        self.assertEqual(ui._stream_title, "Generating response")
        self.assertEqual(ui._stream_answer_buffer, "")
        self.assertEqual(ui._stream_rendered_length, 0)

    def test_plain_output_stream_writes_immediately(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = None

        stderr = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = stderr
        try:
            ui.start_template("template.md", "output.md", 1)
            ui.section_generating("SUMMARY", "one sentence", force=False)
            ui.phase("Draft")
            ui.answer("Hello")
            ui.answer(" world")
            ui.stream_done()
        finally:
            sys.stderr = original_stderr

        output = stderr.getvalue()
        self.assertIn("Draft | [1/1] SUMMARY", output)
        self.assertIn("Hello world\n", output)

    def test_complete_includes_stats_summary_in_plain_output(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = None

        stderr = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = stderr
        try:
            ui.configure_run(
                api_base="http://localhost:11434/v1",
                cache_path="cache.json",
                thinking=False,
                stream=True,
                force=False,
            )
            ui.start_template("template.md", "output.md", 1)
            ui.section_done("SUMMARY", "generated", "word " * 70)
            ui.complete("output.md")
        finally:
            sys.stderr = original_stderr

        output = stderr.getvalue()
        self.assertIn("Saved: output.md", output)
        self.assertIn("generated=1", output)
        self.assertIn("cached=0", output)

    def test_format_elapsed_uses_smart_units(self):
        self.assertEqual(CliUI._format_elapsed(12.4), "12.4s")
        self.assertEqual(CliUI._format_elapsed(350), "5m 50s")
        self.assertEqual(CliUI._format_elapsed(3661), "1h 1m 1s")


if __name__ == "__main__":
    unittest.main()