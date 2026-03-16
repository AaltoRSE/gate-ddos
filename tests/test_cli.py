import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.cli import Application, parse_args


class CliRunTests(unittest.TestCase):
    def test_parse_args_uses_env_only_for_secret_api_key(self):
        with patch.dict(os.environ, { "GATE_DDOS_MODEL": "env-model", "GATE_DDOS_API_KEY": "secret-token" }, clear=False):
            args = parse_args(["SYSTEM.md", "TEMPLATE.md"])

        self.assertEqual(args.model, "qwen3.5:9b")
        self.assertEqual(args.api_key, "secret-token")

    def test_parse_args_loads_json_config_phase_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "model": "config-model",
                        "backend": "openai",
                        "apiBase": "http://localhost:4000/v1",
                        "llm": {
                            "thinking": True,
                            "stream": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            args = parse_args(["--config", str(config_path), "SYSTEM.md", "TEMPLATE.md"])

            self.assertEqual(args.model, "config-model")
            self.assertEqual(args.backend, "openai")
            self.assertEqual(args.api_base, "http://localhost:4000/v1")
            self.assertTrue(args.thinking)
            self.assertFalse(args.stream)

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

            with patch("gate_ddos.cli.DocxPipeline") as mock_pipeline_cls:
                mock_pipeline_cls.return_value.process.side_effect = PermissionError("denied")
                with patch("gate_ddos.cli.write_json_store") as write_json_mock:
                    with self.assertRaises(PermissionError):
                        Application(Args).run()

                    write_json_mock.assert_called_once()

    def test_run_writes_json_when_generation_is_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.md"
            system_path.write_text("System", encoding="utf-8")

            template_path = Path(tmp) / "template.md"
            template_path.write_text("{{ SUMMARY || one sentence }}", encoding="utf-8")

            json_path = Path(tmp) / "run-data.json"
            output_path = Path(tmp) / "output.md"

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

            with patch("gate_ddos.cli.TextPipeline") as mock_pipeline_cls:
                mock_pipeline_cls.return_value.process.side_effect = KeyboardInterrupt
                with patch("gate_ddos.cli.write_json_store") as write_json_mock:
                    with self.assertRaises(KeyboardInterrupt):
                        Application(Args).run()

                    write_json_mock.assert_called_once_with(str(json_path), ANY, "test-model")

    def test_run_generates_markdown_from_text_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.md"
            system_path.write_text("System", encoding="utf-8")

            template_path = Path(tmp) / "template.md"
            template_path.write_text("# Title\n\n{{ SUMMARY || one sentence }}\n", encoding="utf-8")

            output_path = Path(tmp) / "output.md"

            class Args:
                system_prompt = str(system_path)
                template = str(template_path)
                output = str(output_path)
                model = "test-model"
                json = None
                open_delim = "{{"
                close_delim = "}}"
                separator = "||"
                force = False

            mock_generator = MagicMock()
            mock_generator.generate.return_value = "Professional summary"

            with patch("gate_ddos.cli.create_backend"):
                with patch("gate_ddos.cli.LLMGenerator", return_value=mock_generator):
                    Application(Args).run()

            text = output_path.read_text(encoding="utf-8")
            self.assertIn("Professional summary", text)

    def test_run_rejects_mismatched_template_and_output_extensions(self):
        cases = [
            ("template.docx", b"docx-bytes", "output.txt"),
            ("template.txt", "{{ SUMMARY || one sentence }}", "output.docx"),
        ]

        for template_name, template_content, output_name in cases:
            with self.subTest(template_name=template_name, output_name=output_name):
                with tempfile.TemporaryDirectory() as tmp:
                    system_path = Path(tmp) / "system.md"
                    system_path.write_text("System", encoding="utf-8")

                    template_path = Path(tmp) / template_name
                    if isinstance(template_content, bytes):
                        template_path.write_bytes(template_content)
                    else:
                        template_path.write_text(template_content, encoding="utf-8")

                    class Args:
                        system_prompt = str(system_path)
                        template = str(template_path)
                        output = str(Path(tmp) / output_name)
                        model = "test-model"
                        json = None
                        open_delim = "{{"
                        close_delim = "}}"
                        separator = "||"
                        force = False

                    with self.assertRaises(ValueError):
                        Application(Args).run()

    def test_run_backend_ollama_enables_native_transport_without_forcing_thinking(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.md"
            system_path.write_text("System", encoding="utf-8")

            template_path = Path(tmp) / "template.md"
            template_path.write_text("{{ SUMMARY || one sentence }}", encoding="utf-8")

            output_path = Path(tmp) / "output.md"

            backend_kwargs = {}
            generator_kwargs = {}

            class Args:
                system_prompt = str(system_path)
                template = str(template_path)
                output = str(output_path)
                model = "test-model"
                backend = "ollama"
                json = None
                open_delim = "{{"
                close_delim = "}}"
                separator = "||"
                force = False
                thinking = False

            mock_generator = MagicMock()
            mock_generator.generate.return_value = "x"

            def capture_backend(*args, **kwargs):
                backend_kwargs.update(kwargs)
                return MagicMock()

            def capture_generator(*args, **kwargs):
                generator_kwargs.update(kwargs)
                return mock_generator

            with patch("gate_ddos.cli.create_backend", side_effect=capture_backend):
                with patch("gate_ddos.cli.LLMGenerator", side_effect=capture_generator):
                    Application(Args).run()

            self.assertFalse(generator_kwargs.get("enable_thinking"))
            self.assertTrue(backend_kwargs.get("prefer_ollama"))

    def test_run_backend_openai_disables_native_and_thinking(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.md"
            system_path.write_text("System", encoding="utf-8")

            template_path = Path(tmp) / "template.md"
            template_path.write_text("{{ SUMMARY || one sentence }}", encoding="utf-8")

            output_path = Path(tmp) / "output.md"

            backend_kwargs = {}
            generator_kwargs = {}

            class Args:
                system_prompt = str(system_path)
                template = str(template_path)
                output = str(output_path)
                model = "test-model"
                api_base = "http://localhost:11434/v1"
                backend = "openai"
                json = None
                open_delim = "{{"
                close_delim = "}}"
                separator = "||"
                force = False
                thinking = True

            mock_generator = MagicMock()
            mock_generator.generate.return_value = "x"

            def capture_backend(*args, **kwargs):
                backend_kwargs.update(kwargs)
                return MagicMock()

            def capture_generator(*args, **kwargs):
                generator_kwargs.update(kwargs)
                return mock_generator

            with patch("gate_ddos.cli.create_backend", side_effect=capture_backend):
                with patch("gate_ddos.cli.LLMGenerator", side_effect=capture_generator):
                    Application(Args).run()

            self.assertFalse(backend_kwargs.get("prefer_ollama"))
            self.assertTrue(generator_kwargs.get("enable_thinking"))

    def test_run_passes_stream_setting_to_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = Path(tmp) / "system.md"
            system_path.write_text("System", encoding="utf-8")

            template_path = Path(tmp) / "template.md"
            template_path.write_text("{{ SUMMARY || one sentence }}", encoding="utf-8")

            output_path = Path(tmp) / "output.md"

            generator_kwargs = {}

            class Args:
                system_prompt = str(system_path)
                template = str(template_path)
                output = str(output_path)
                model = "test-model"
                backend = "ollama"
                api_base = "http://localhost:11434/v1"
                json = None
                open_delim = "{{"
                close_delim = "}}"
                separator = "||"
                force = False
                thinking = False
                stream = False

            mock_generator = MagicMock()
            mock_generator.generate.return_value = "x"

            def capture_generator(*args, **kwargs):
                generator_kwargs.update(kwargs)
                return mock_generator

            with patch("gate_ddos.cli.create_backend"):
                with patch("gate_ddos.cli.LLMGenerator", side_effect=capture_generator):
                    Application(Args).run()

            self.assertFalse(generator_kwargs.get("stream"))


if __name__ == "__main__":
    unittest.main()
