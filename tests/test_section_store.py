import unittest
import sys
from pathlib import Path
from typing import Callable, cast

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.models import SectionRecord
from gate_ddos.section_store import SectionStore


class SectionStoreTests(unittest.TestCase):
    def test_resolve_generates_and_stores_record(self):
        store = SectionStore()
        calls = []

        def generator(prompt):
            calls.append(prompt)
            return "generated"

        value = store.resolve("SUMMARY", "Prompt", generator)

        self.assertEqual(value, "generated")
        self.assertEqual(calls, ["Prompt"])
        self.assertIn("SUMMARY", store.records)
        self.assertEqual(store.records["SUMMARY"].source, "llm")

    def test_resolve_reuses_existing_promptless_json_record(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="From JSON", source="json")})
        value = store.resolve("FOOTER", "Footer prompt", lambda _: "new")

        self.assertEqual(value, "From JSON")
        self.assertEqual(store.records["FOOTER"].prompt, "Footer prompt")

    def test_resolve_key_only_returns_empty_when_missing(self):
        store = SectionStore()
        value = store.resolve("FOOTER", None, None)
        self.assertEqual(value, "")

    def test_resolve_key_only_returns_existing_output(self):
        store = SectionStore({"FOOTER": SectionRecord(prompt="", output="Footer text", source="json")})
        value = store.resolve("FOOTER", None, None)
        self.assertEqual(value, "Footer text")

    def test_resolve_regenerates_on_prompt_mismatch(self):
        store = SectionStore({"SUMMARY": SectionRecord(prompt="Prompt A", output="A", source="json")})

        value = store.resolve("SUMMARY", "Prompt B", lambda _: "new")

        self.assertEqual(value, "new")
        self.assertEqual(store.records["SUMMARY"].prompt, "Prompt B")
        self.assertEqual(store.records["SUMMARY"].output, "new")
        self.assertEqual(store.records["SUMMARY"].source, "llm")

    def test_resolve_force_generate_overrides_cached_prompted_section(self):
        store = SectionStore({"SUMMARY": SectionRecord(prompt="Prompt", output="cached", source="json")})
        value = store.resolve("SUMMARY", "Prompt", lambda _: "fresh", force_generate=True)

        self.assertEqual(value, "fresh")
        self.assertEqual(store.records["SUMMARY"].output, "fresh")
        self.assertEqual(store.records["SUMMARY"].source, "llm")

    def test_resolve_raises_when_generator_is_none(self):
        store = SectionStore()
        with self.assertRaises(ValueError):
            store.resolve("MISSING", "Prompt", None)

    def test_resolve_raises_when_generator_returns_none(self):
        store = SectionStore()
        with self.assertRaises(RuntimeError):
            store.resolve("MISSING", "Prompt", cast(Callable[[str], str], lambda _: None))


if __name__ == "__main__":
    unittest.main()
