import warnings
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.models import SectionRecord, TemplateSyntax
from gate_ddos.section_store import SectionStore
from gate_ddos.template_engine import TemplateEngine, count_placeholders, parse_placeholder


class TemplateEngineTests(unittest.TestCase):
    def setUp(self):
        self.syntax = TemplateSyntax()

    def _engine(self, store, generate, *, force=False, ui=None):
        return TemplateEngine("sys", self.syntax, store, generate, force=force, ui=ui)

    def test_parse_placeholder_variants(self):
        cases = [
            ("SUMMARY || Write summary", ("SUMMARY", "Write summary")),
            ("FOOTER", ("FOOTER", None)),
            ("system info || short prompt", ("system info", "short prompt")),
        ]

        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_placeholder(raw, self.syntax), expected)

    def test_parse_placeholder_invalid_empty(self):
        with self.assertRaises(ValueError):
            parse_placeholder("   ", self.syntax)

    def test_build_replacer_uses_json_for_key_only(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return "should-not-be-used"

        result = self._engine(store, fake_generate).replace("Before {{ FOOTER }} After")

        self.assertEqual(result, "Before Footer text After")
        self.assertEqual(calls, [])

    def test_build_replacer_generates_when_missing(self):
        store = SectionStore()

        def fake_generate(system_prompt, prompt):
            return "Generated"

        result = self._engine(store, fake_generate).replace("{{ SUMMARY || Prompt }}")

        self.assertEqual(result, "Generated")
        self.assertIn("SUMMARY", store.records)

    def test_replace_ignores_non_matching_placeholder_shapes(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return "Generated"

        cases = [
            "Before {{FOOTER}} After",
            "Before {{{ FOOTER }}} After",
        ]

        for text in cases:
            with self.subTest(text=text):
                result = self._engine(store, fake_generate).replace(text)
                self.assertEqual(result, text)

        self.assertEqual(calls, [])

    def test_build_replacer_force_regenerates_prompted_cache(self):
        store = SectionStore({"SUMMARY": SectionRecord(prompt="Prompt", output="Cached", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return "Fresh"

        result = self._engine(store, fake_generate, force=True).replace("{{ SUMMARY || Prompt }}")

        self.assertEqual(result, "Fresh")
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.records["SUMMARY"].output, "Fresh")
        self.assertEqual(store.records["SUMMARY"].source, "llm")

    def test_build_replacer_force_keeps_key_only_behavior(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return "Fresh"

        result = self._engine(store, fake_generate, force=True).replace("Before {{ FOOTER }} After")

        self.assertEqual(result, "Before Footer text After")
        self.assertEqual(calls, [])

    def test_build_replacer_regenerates_when_cache_prompt_changed(self):
        store = SectionStore({"SUMMARY": SectionRecord(prompt="Prompt A", output="Cached", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return "Fresh"

        result = self._engine(store, fake_generate).replace("{{ SUMMARY || Prompt B }}")

        self.assertEqual(result, "Fresh")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "sys")
        self.assertIn("Prompt B", calls[0][1])
        self.assertEqual(store.records["SUMMARY"].prompt, "Prompt B")
        self.assertEqual(store.records["SUMMARY"].output, "Fresh")

    def test_build_replacer_warns_when_same_key_has_multiple_prompts_in_document(self):
        store = SectionStore()
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return f"Generated for {prompt}"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = self._engine(store, fake_generate).replace("{{ NAME || Prompt A }} and {{ NAME || Prompt B }}")

        self.assertEqual(result, "Generated for Prompt A and {{ NAME || Prompt B }}")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "sys")
        self.assertIn("Prompt A", calls[0][1])
        self.assertTrue(any("multiple different prompts in the same document" in str(warning.message) for warning in w))

    def test_build_replacer_reuses_same_key_and_prompt_in_document(self):
        store = SectionStore()
        calls = []

        def fake_generate(system_prompt, prompt):
            calls.append((system_prompt, prompt))
            return "Generated"

        result = self._engine(store, fake_generate).replace("{{ NAME || Prompt }} and {{ NAME || Prompt }}")

        self.assertEqual(result, "Generated and Generated")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "sys")
        self.assertIn("Prompt", calls[0][1])

    def test_build_replacer_passes_plain_prompts_for_later_sections(self):
        store = SectionStore()
        prompts = []

        def fake_generate(system_prompt, prompt):
            prompts.append(prompt)
            return "Generated"

        self._engine(store, fake_generate).replace("{{ INTRO || Write a short introduction. }}\n{{ DETAIL || Expand on the introduction with more detail. }}")

        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0], "Write a short introduction.")
        self.assertEqual(prompts[1], "Expand on the introduction with more detail.")

    def test_build_replacer_survives_generation_error(self):
        """A failing generator should leave the placeholder intact, not crash."""
        store = SectionStore()

        def bad_generate(system_prompt, prompt):
            raise RuntimeError("LLM exploded")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = self._engine(store, bad_generate).replace("Before {{ BOOM || Prompt }} After")

        self.assertIn("{{ BOOM || Prompt }}", result)
        self.assertTrue(any("BOOM" in str(warning.message) for warning in w))

    def test_count_placeholders_counts_multiline_matches(self):
        text = "{{ A || First }}\n\n{{ B || Multi\nline }}\n{{ C }}"
        self.assertEqual(count_placeholders(text, self.syntax), 3)

    def test_build_replacer_reports_detailed_ui_events(self):
        store = SectionStore()
        ui = Mock()

        def fake_generate(system_prompt, prompt):
            return "Generated"

        result = self._engine(store, fake_generate, force=True, ui=ui).replace("{{ SUMMARY || Prompt text }}")

        self.assertEqual(result, "Generated")
        ui.section_generating.assert_called_once_with("SUMMARY", "Prompt text", force=True)
        ui.section_done.assert_called_once_with("SUMMARY", "generated", "Generated")


if __name__ == "__main__":
    unittest.main()
