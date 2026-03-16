import re
import time
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from .. import constants as _constants
from ..ui import CliUI
from .backend import LLMBackend, ThinkValue, create_backend

DEFAULT_API_BASE = "http://localhost:11434/v1"

_THINK_TAG_PATTERNS = [
    re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL),
    re.compile(r"<thinking>.*?</thinking>", re.IGNORECASE | re.DOTALL),
]


def _strip_thinking_trace(text: str) -> str:
    """Remove common inline reasoning-trace tags from model output."""
    cleaned = text
    for pattern in _THINK_TAG_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


LLM_MAX_RETRIES = _constants.LLM_MAX_RETRIES
LLM_RETRY_DELAY = _constants.LLM_RETRY_DELAY
LLM_STREAM = _constants.LLM_STREAM
LLM_THINKING = _constants.LLM_THINKING


class LLMGenerator:
    """Orchestrates single-pass LLM generation with retries."""

    def __init__(
        self,
        backend: LLMBackend,
        model: str,
        *,
        enable_thinking: bool = False,
        stream: bool = LLM_STREAM,
        ui: CliUI | None = None,
    ):
        self.backend = backend
        self.model = model
        self.enable_thinking = enable_thinking
        self.stream = stream
        self.ui = ui

    def generate(self, system_prompt: str, prompt: str) -> str:
        """Generate text in a single pass."""
        if not prompt or not prompt.strip():
            raise ValueError("LLM prompt must not be empty")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        if self.ui is not None:
            self.ui.phase("Section", stream_title="Draft")
        return self._chat(
            messages,
            stream=self.stream,
            phase="draft",
            enable_thinking=self.enable_thinking,
        )

    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool,
        phase: str,
        enable_thinking: bool,
        render: bool = True,
    ) -> str:
        """Run a single chat request with retries."""
        last_error: Exception | None = None
        think_value = self._resolve_think_value(enable_thinking)

        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                response = self.backend.request(self.model, messages, stream=stream, think=think_value)
                result = self._finalize(
                    self._read_response(response, stream=stream, enable_thinking=enable_thinking),
                    enable_thinking=enable_thinking,
                )
                if not result:
                    raise RuntimeError(
                        f"LLM returned an empty response during '{phase}' for model '{self.model}'. "
                        "Check that the model is loaded and the prompt is valid."
                    )
                if render:
                    self._render(result, phase=phase, stream=stream, enable_thinking=enable_thinking)
                return result
            except Exception as exc:
                last_error = exc
                retry_label = self._retry_label(exc)
                if retry_label is None:
                    raise
                if attempt < LLM_MAX_RETRIES:
                    self._log_retry(retry_label, phase, attempt, exc)
                    time.sleep(LLM_RETRY_DELAY)

        raise ConnectionError(
            f"Failed to connect to LLM after {LLM_MAX_RETRIES} attempts during '{phase}'. "
            f"Last error: {last_error}"
        )

    def _read_response(self, response: Any, *, stream: bool, enable_thinking: bool) -> str:
        """Collect response text from streaming or non-streaming responses."""
        if not stream:
            return self.backend.extract_response(response).strip()

        chunks: list[str] = []
        for part in response:
            self._emit_thinking(part, enable_thinking=enable_thinking)
            content = self.backend.extract_content(part)
            if not content:
                continue
            chunks.append(content)
            if self.ui is not None:
                self.ui.answer(content)
        return "".join(chunks).strip()

    def _emit_thinking(self, part: Any, *, enable_thinking: bool) -> None:
        """Render a thinking chunk when enabled and supported."""
        if not (self.backend.supports_thinking and enable_thinking):
            return

        thinking = self.backend.extract_thinking(part)
        if not thinking:
            return

        if self.ui is not None:
            self.ui.thinking(thinking)
            return

        print(thinking, end="", flush=True)

    def _finalize(self, raw_result: str, *, enable_thinking: bool) -> str:
        """Apply final cleanup rules to the generated text."""
        if enable_thinking or not raw_result:
            return raw_result
        stripped = _strip_thinking_trace(raw_result)
        return stripped or raw_result

    def _render(self, result: str, *, phase: str, stream: bool, enable_thinking: bool = False) -> None:
        """Render the final response according to current output mode."""
        if self.ui is None:
            if stream:
                if (not (self.backend.supports_thinking and enable_thinking) and result):
                    print(result, end="", flush=True)
                print("\n--- Done ---\n")
            return

        if stream:
            self.ui.stream_done()
            return
        self.ui.render_markdown(phase.title(), result)

    def _retry_label(self, exc: Exception) -> str | None:
        """Return a retry label for transient failures, else re-raise/skip."""
        if isinstance(exc, APIStatusError):
            status_code = getattr(exc, "status_code", None)
            if not (status_code in (408, 409, 429) or status_code is None or status_code >= 500):
                raise RuntimeError(f"LLM request failed with status {status_code}: {exc}") from exc
            return "Transient API error"
        if isinstance(exc, (OSError, APIConnectionError, APITimeoutError, RateLimitError)):
            return "Connection error"
        return "Ollama error" if self.backend.__class__.__name__ == "OllamaBackend" else None

    def _log_retry(self, kind: str, phase: str, attempt: int, exc: Exception) -> None:
        """Log retry details and wait before the next attempt."""
        if self.ui is not None:
            self.ui.retry(kind, phase, attempt, LLM_MAX_RETRIES, LLM_RETRY_DELAY, exc)
        else:
            print(
                f"\n  {kind} in '{phase}' (attempt {attempt}/{LLM_MAX_RETRIES}): {exc}"
                f"\n  Retrying in {LLM_RETRY_DELAY}s...\n"
            )

    def _resolve_think_value(self, enable_thinking: bool) -> ThinkValue:
        """Resolve think value for model families with custom controls."""
        if self.model.strip().lower().startswith("gpt-oss"):
            return "medium" if enable_thinking else "low"
        return enable_thinking


def generate(
    system_prompt: str,
    prompt: str,
    model: str,
    *,
    api_base: str | None = None,
    api_key: str | None = None,
    enable_thinking: bool | None = None,
    stream: bool | None = None,
    prefer_ollama_native: bool = False,
    ui: CliUI | None = None,
) -> str:
    """Generate text in a single pass.

    Convenience wrapper that creates the appropriate backend and generator.
    """
    resolved_api_base = (api_base or DEFAULT_API_BASE).strip()
    if not resolved_api_base:
        raise ValueError("API base URL must not be empty")

    thinking_enabled = LLM_THINKING if enable_thinking is None else enable_thinking
    resolved_stream = LLM_STREAM if stream is None else stream

    backend = create_backend(resolved_api_base, api_key, prefer_ollama=prefer_ollama_native)
    generator = LLMGenerator(backend, model, enable_thinking=thinking_enabled, stream=resolved_stream, ui=ui)
    return generator.generate(system_prompt, prompt)
