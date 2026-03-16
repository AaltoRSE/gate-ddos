import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_ddos.llm.backend import create_backend
from gate_ddos.llm.generator import LLMGenerator, _strip_thinking_trace, generate
from gate_ddos.llm.ollama_backend import OllamaBackend
from gate_ddos.llm.openai_backend import OpenAIBackend


class _Message:
    def __init__(self, content: str):
        self.content = content


class _ChoiceMessage:
    def __init__(self, content: str):
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str):
        self.choices = [_ChoiceMessage(content)]


class _ChatCompletions:
    def __init__(self, create_fn):
        self.create = create_fn


class _Chat:
    def __init__(self, create_fn):
        self.completions = _ChatCompletions(create_fn)


class _Client:
    def __init__(self, create_fn):
        self.chat = _Chat(create_fn)


class _OllamaClient:
    def __init__(self, chat_fn):
        self._chat_fn = chat_fn

    def chat(self, **kwargs):
        return self._chat_fn(**kwargs)


class LlmGenerationTests(unittest.TestCase):
    def test_render_lets_ui_finalize_streamed_output(self):
        ui = Mock()
        backend = OpenAIBackend("http://localhost:11434/v1")
        generator = LLMGenerator(backend, "test-model", ui=ui)

        generator._render("# Title\n\n- one\n- two", phase="draft", stream=True)

        ui.stream_done.assert_called_once_with()
        ui.render_markdown.assert_not_called()

    def test_strip_thinking_trace_removes_think_tags(self):
        text = "<think>internal trace</think>Final answer"
        self.assertEqual(_strip_thinking_trace(text), "Final answer")

    def test_strip_thinking_trace_keeps_regular_text(self):
        text = "Final answer without trace"
        self.assertEqual(_strip_thinking_trace(text), text)

    def test_generate_uses_single_non_stream_request(self):
        cases = [
            (
                "default_non_stream_setting",
                {"patch_stream_default": False, "kwargs": {}},
                "Draft content",
            ),
            (
                "explicit_stream_override",
                {"patch_stream_default": None, "kwargs": {"stream": False}},
                "Only draft",
            ),
        ]

        for label, config, payload in cases:
            calls = []

            def fake_create(*, model, messages, stream, _calls=calls, _payload=payload, **kwargs):
                _calls.append(stream)
                return _Response(_payload)

            with self.subTest(label):
                with patch.object(OpenAIBackend, "_create_client", return_value=_Client(fake_create)):
                    if config["patch_stream_default"] is False:
                        with patch("gate_ddos.llm.generator.LLM_STREAM", False):
                            result = generate("sys", "question", "model-x", **config["kwargs"])
                    else:
                        result = generate("sys", "question", "model-x", **config["kwargs"])

            self.assertEqual(result, payload)
            self.assertEqual(calls, [False])

    def test_generate_handles_non_stream_response_object(self):
        backend = OpenAIBackend("http://localhost:11434/v1")
        generator = LLMGenerator(backend, "test-model", stream=False)

        with patch.object(backend, "request", return_value=_Response("Draft content")) as request_mock:
            result = generator.generate("sys", "question")

        self.assertEqual(result, "Draft content")
        request_mock.assert_called_once()

    def test_generate_passes_api_base_and_key_to_backend(self):
        def fake_create(*, model, messages, stream, **kwargs):
            return _Response("Draft content")

        backends_created = []
        original_create_backend = create_backend

        def spy_create_backend(api_base, api_key=None, *, prefer_ollama=False):
            backend = original_create_backend(api_base, api_key, prefer_ollama=prefer_ollama)
            backends_created.append(backend)
            return backend

        with patch.object(OpenAIBackend, "_create_client", return_value=_Client(fake_create)):
            with patch("gate_ddos.llm.generator.create_backend", side_effect=spy_create_backend) as mock_cb:
                with patch("gate_ddos.llm.generator.LLM_STREAM", False):
                    result = generate(
                        "sys",
                        "question",
                        "model-x",
                        api_base="http://localhost:4000/v1",
                        api_key="secret-token",
                    )

        self.assertEqual(result, "Draft content")
        mock_cb.assert_called_once_with("http://localhost:4000/v1", "secret-token", prefer_ollama=False)

    def test_generate_thinking_mode_sends_think_extension(self):
        captured_kwargs = {}

        def fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return _Response("Draft content")

        with patch.object(OpenAIBackend, "_create_client", return_value=_Client(fake_create)):
            with patch("gate_ddos.llm.generator.LLM_STREAM", False):
                result = generate(
                    "sys",
                    "question",
                    "model-x",
                    enable_thinking=True,
                )

        self.assertEqual(result, "Draft content")
        self.assertEqual(
            captured_kwargs.get("extra_body"),
            {"think": True, "options": {"think": True}},
        )

    def test_generate_no_thinking_mode_sends_think_false_extension(self):
        captured_kwargs = {}

        def fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return _Response("Draft content")

        with patch.object(OpenAIBackend, "_create_client", return_value=_Client(fake_create)):
            with patch("gate_ddos.llm.generator.LLM_STREAM", False):
                result = generate(
                    "sys",
                    "question",
                    "model-x",
                    enable_thinking=False,
                )

        self.assertEqual(result, "Draft content")
        self.assertEqual(
            captured_kwargs.get("extra_body"),
            {"think": False, "options": {"think": False}},
        )

    def test_generate_gpt_oss_uses_think_levels_instead_of_bools(self):
        captured_kwargs = {}

        def fake_create(**kwargs):
            captured_kwargs.update(kwargs)
            return _Response("Draft content")

        with patch.object(OpenAIBackend, "_create_client", return_value=_Client(fake_create)):
            with patch("gate_ddos.llm.generator.LLM_STREAM", False):
                result = generate(
                    "sys",
                    "question",
                    "gpt-oss:20b",
                    enable_thinking=False,
                )

        self.assertEqual(result, "Draft content")
        self.assertEqual(
            captured_kwargs.get("extra_body"),
            {"think": "low", "options": {"think": "low"}},
        )

    def test_generate_can_use_native_ollama_transport(self):
        captured = {}

        def fake_chat(**kwargs):
            captured.update(kwargs)
            return {"message": {"content": "Draft content"}}

        with patch("gate_ddos.llm.ollama_backend.OllamaSDK", side_effect=lambda host: _OllamaClient(fake_chat)):
            with patch("gate_ddos.llm.generator.LLM_STREAM", False):
                result = generate(
                    "sys",
                    "question",
                    "qwen3.5:9b",
                    api_base="http://localhost:11434/v1",
                    enable_thinking=False,
                    prefer_ollama_native=True,
                )

        self.assertEqual(result, "Draft content")
        self.assertFalse(captured.get("think"))

if __name__ == "__main__":
    unittest.main()
