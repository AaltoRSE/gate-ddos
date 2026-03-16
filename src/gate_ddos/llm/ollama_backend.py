from typing import Any, cast
from urllib.parse import urlparse, urlunparse

from .backend import LLMBackend, lookup_path

try:
    from ollama import Client as OllamaSDK
except Exception:
    OllamaSDK = None


class OllamaBackend(LLMBackend):
    """Native Ollama SDK backend with thinking/reasoning support."""

    def _create_client(self):
        if OllamaSDK is None:
            raise RuntimeError(
                "Ollama native mode requested, but the 'ollama' package is not installed. "
                "Install dependencies from requirements.txt."
            )
        return OllamaSDK(host=self._normalize_host())

    @property
    def supports_thinking(self) -> bool:
        return True

    def request(self, model, messages, *, stream, think):
        if stream:
            return self.client.chat(model=model, messages=cast(Any, messages), stream=True, think=think)
        return self.client.chat(model=model, messages=cast(Any, messages), think=think)

    def extract_content(self, chunk):
        return self._extract_field(chunk, "content")

    def extract_response(self, response):
        return self.extract_content(response)

    def extract_thinking(self, chunk):
        return self._extract_field(chunk, "thinking")

    def _normalize_host(self) -> str:
        """Convert OpenAI-style /v1 URL into native Ollama host URL."""
        parsed = urlparse(self.api_base)
        if not parsed.scheme or not parsed.netloc:
            return self.api_base.rstrip("/")
        path = parsed.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        normalized = parsed._replace(path=path, params="", query="", fragment="")
        return urlunparse(normalized).rstrip("/")

    def _extract_field(self, part: Any, field: str) -> str:
        for search_path in (("message", field), (field,)):
            value = lookup_path(part, *search_path)
            if isinstance(value, str):
                return value
        return ""
