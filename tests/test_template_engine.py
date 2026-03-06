import warnings
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.models import SectionRecord, TemplateSyntax
from gate_ddos.section_store import SectionStore
from gate_ddos.template_engine import parse_placeholder, build_replacer


class TemplateEngineTests(unittest.TestCase):
    def setUp(self):
        self.syntax = TemplateSyntax()

    def test_parse_placeholder_with_prompt(self):
        key, prompt = parse_placeholder("SUMMARY || Write summary", self.syntax)
        self.assertEqual(key, "SUMMARY")
        self.assertEqual(prompt, "Write summary")

    def test_parse_placeholder_key_only(self):
        key, prompt = parse_placeholder("FOOTER", self.syntax)
        self.assertEqual(key, "FOOTER")
        self.assertIsNone(prompt)

    def test_parse_placeholder_allows_space_and_lowercase_key(self):
        key, prompt = parse_placeholder("system info || short prompt", self.syntax)
        self.assertEqual(key, "system info")
        self.assertEqual(prompt, "short prompt")

    def test_parse_placeholder_invalid_empty(self):
        with self.assertRaises(ValueError):
            parse_placeholder("   ", self.syntax)

    def test_build_replacer_uses_json_for_key_only(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt, model):
            calls.append((system_prompt, prompt, model))
            return "should-not-be-used"

        replacer = build_replacer("sys", "model", self.syntax, store, fake_generate)
        result = replacer("Before {{ FOOTER }} After")

        self.assertEqual(result, "Before Footer text After")
        self.assertEqual(calls, [])

    def test_build_replacer_generates_when_missing(self):
        store = SectionStore()

        def fake_generate(system_prompt, prompt, model):
            return "Generated"

        replacer = build_replacer("sys", "model", self.syntax, store, fake_generate)
        result = replacer("{{ SUMMARY || Prompt }}")

        self.assertEqual(result, "Generated")
        self.assertIn("SUMMARY", store.records)

    def test_build_replacer_does_not_match_without_inner_spaces(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt, model):
            calls.append((system_prompt, prompt, model))
            return "Generated"

        replacer = build_replacer("sys", "model", self.syntax, store, fake_generate)
        result = replacer("Before {{FOOTER}} After")

        self.assertEqual(result, "Before {{FOOTER}} After")
        self.assertEqual(calls, [])

    def test_build_replacer_does_not_match_triple_braces(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt, model):
            calls.append((system_prompt, prompt, model))
            return "Generated"

        replacer = build_replacer("sys", "model", self.syntax, store, fake_generate)
        result = replacer("Before {{{ FOOTER }}} After")

        self.assertEqual(result, "Before {{{ FOOTER }}} After")
        self.assertEqual(calls, [])

    def test_build_replacer_force_regenerates_prompted_cache(self):
        store = SectionStore({"SUMMARY": SectionRecord(prompt="Prompt", output="Cached", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt, model):
            calls.append((system_prompt, prompt, model))
            return "Fresh"

        replacer = build_replacer("sys", "model", self.syntax, store, fake_generate, force=True)
        result = replacer("{{ SUMMARY || Prompt }}")

        self.assertEqual(result, "Fresh")
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.records["SUMMARY"].output, "Fresh")
        self.assertEqual(store.records["SUMMARY"].source, "llm")

    def test_build_replacer_force_keeps_key_only_behavior(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        calls = []

        def fake_generate(system_prompt, prompt, model):
            calls.append((system_prompt, prompt, model))
            return "Fresh"

        replacer = build_replacer("sys", "model", self.syntax, store, fake_generate, force=True)
        result = replacer("Before {{ FOOTER }} After")

        self.assertEqual(result, "Before Footer text After")
        self.assertEqual(calls, [])

    def test_build_replacer_survives_generation_error(self):
        """A failing generator should leave the placeholder intact, not crash."""
        store = SectionStore()

        def bad_generate(system_prompt, prompt, model):
            raise RuntimeError("LLM exploded")

        replacer = build_replacer("sys", "model", self.syntax, store, bad_generate)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = replacer("Before {{ BOOM || Prompt }} After")

        self.assertIn("{{ BOOM || Prompt }}", result)
        self.assertTrue(any("BOOM" in str(warning.message) for warning in w))


if __name__ == "__main__":
    unittest.main()
