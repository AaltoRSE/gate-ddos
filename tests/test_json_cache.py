import json
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.json_cache import records_from_payload, read_json_store, write_json_store
from gate_ddos.models import SectionRecord
from gate_ddos.section_store import SectionStore


class JsonCacheTests(unittest.TestCase):
    def test_records_from_payload_sections_object(self):
        payload = {
            "sections": {
                "SUMMARY": {
                    "prompt": "Prompt",
                    "output": "Output",
                }
            }
        }

        records = records_from_payload(payload)
        self.assertIn("SUMMARY", records)
        self.assertEqual(records["SUMMARY"].prompt, "Prompt")
        self.assertEqual(records["SUMMARY"].output, "Output")

    def test_records_from_payload_simple_mapping(self):
        payload = {"FOOTER": "Footer text"}
        records = records_from_payload(payload)
        self.assertEqual(records["FOOTER"].output, "Footer text")

    def test_records_from_payload_invalid_top_level(self):
        with self.assertRaises(ValueError):
            records_from_payload(["not", "an", "object"])

    def test_write_json_store_creates_expected_shape(self):
        store = SectionStore({"SUMMARY": SectionRecord(prompt="Prompt", output="Output", source="llm")})

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "run-data.json"
            write_json_store(str(out_path), store, "test-model")

            content = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(content["version"], 1)
            self.assertEqual(content["model"], "test-model")
            self.assertIn("SUMMARY", content["sections"])

    def test_write_json_store_creates_parent_dirs(self):
        store = SectionStore({"A": SectionRecord(prompt="p", output="o", source="llm")})
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "sub" / "dir" / "data.json"
            write_json_store(str(out_path), store, "m")
            self.assertTrue(out_path.exists())

    def test_write_json_store_atomic_does_not_leave_tmp_on_failure(self):
        store = SectionStore({"A": SectionRecord(prompt="p", output="o", source="llm")})
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "data.json"
            write_json_store(str(out_path), store, "m")
            # tmp file should be cleaned up
            self.assertFalse((out_path.with_suffix(".tmp")).exists())

    def test_read_json_store_invalid_json_raises_with_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "bad.json"
            bad_file.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                read_json_store(str(bad_file))
            self.assertIn("line", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
