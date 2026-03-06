import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.cli import run


class CliRunTests(unittest.TestCase):
    def test_run_writes_json_even_when_docx_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.md"
            system_path.write_text("System", encoding="utf-8")

            template_path = Path(tmp) / "template.docx"
            template_path.write_bytes(b"docx-bytes")

            json_path = Path(tmp) / "run-data.json"
            output_path = Path(tmp) / "output.docx"

            class Args:
                system_prompt = str(system_path)
                template = str(template_path)
                output = str(output_path)
                model = "test-model"
                json = str(json_path)
                open_delim = "{{"
                close_delim = "}}"
                separator = "||"
                force = False

            with patch("gate_ddos.cli.process_template_docx", side_effect=PermissionError("denied")):
                with patch("gate_ddos.cli.write_json_store") as write_json_mock:
                    with self.assertRaises(PermissionError):
                        run(Args)

                    write_json_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
