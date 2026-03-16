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

    def test_stream_markdown_renders_formatted_content_inside_panel(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(file=io.StringIO(), width=60, soft_wrap=False, force_terminal=False, color_system=None)
        ui.phase("Draft")

        ui.answer("# Title\n\n- one\n- two\n\n**bold** text")

        renderable = ui._build_stream_renderable()
        self.assertIsNotNone(renderable)

        ui._console.print(renderable)
        console_file = cast(io.StringIO, ui._console.file)
        self.assertIsInstance(console_file, io.StringIO)
        output = console_file.getvalue()

        self.assertIn("Title", output)
        self.assertIn("one", output)
        self.assertIn("two", output)
        self.assertNotIn("# Title", output)
        self.assertNotIn("- one", output)
        self.assertGreater(output.count("\n"), 4)

    def test_phase_can_use_distinct_stream_panel_title(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)

        ui.phase("Generating response", stream_title="Draft")

        self.assertEqual(ui._phase_title, "Generating response")
        self.assertEqual(ui._stream_title, "Draft")

    def test_stream_session_keeps_custom_stream_panel_title(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = Console(file=io.StringIO(), width=60, soft_wrap=False, force_terminal=False, color_system=None)

        ui.phase("Generating response", stream_title="Draft")
        ui.answer("Hello")

        self.assertEqual(ui._phase_title, "Generating response")
        self.assertEqual(ui._stream_title, "Draft")

    def test_tail_stream_lines_keeps_latest_lines(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)

        preview = ui._tail_stream_lines(
            "Line 1\nLine 2\nLine 3\nLine 4\nLine 5",
            max_lines=3,
        )

        self.assertNotIn("Line 1", preview)
        self.assertIn("Line 5", preview)
        self.assertEqual(preview, "Line 3\nLine 4\nLine 5")

    def test_tail_stream_lines_preserves_latest_markdown_block(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)

        preview = ui._tail_stream_lines(
            "Intro\n## Latest heading\n\n- latest item\nFinal paragraph",
            max_lines=3,
        )

        self.assertEqual(preview, "\n- latest item\nFinal paragraph")

    def test_stream_suspends_and_restores_progress(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui.phase("Draft")

        ui.start_template("template.md", "output.md", 2)

        self.assertIsNotNone(ui._progress)
        self.assertEqual(ui._progress_completed, 0)
        assert ui._progress is not None
        self.assertEqual(len(ui._progress.columns), 4)

        ui.answer("Hello")

        self.assertTrue(ui._stream_open)
        self.assertTrue(ui._progress_suspended)
        self.assertIsNone(ui._progress)
        self.assertIsNotNone(ui._stream_live)

        ui.stream_done()

        self.assertFalse(ui._stream_open)
        self.assertFalse(ui._progress_suspended)
        self.assertIsNotNone(ui._progress)
        self.assertIsNone(ui._stream_live)

        ui.close()

    def test_plain_output_stream_writes_immediately(self):
        ui = CliUI(backend="ollama", model="test", enabled=True)
        ui._console = None

        stderr = io.StringIO()
        original_stderr = sys.stderr
        sys.stderr = stderr
        try:
            ui.answer("Hello")
            ui.answer(" world")
            ui.stream_done()
        finally:
            sys.stderr = original_stderr

        self.assertEqual(stderr.getvalue(), "Hello world\n")

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