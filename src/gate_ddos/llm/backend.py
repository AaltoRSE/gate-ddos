from abc import ABC, abstractmethod
from typing import Any, Literal

ThinkValue = bool | Literal["low", "medium", "high"]


def lookup_path(value: Any, *path: str | int) -> Any:
    """Read nested dict/attribute/list values without raising."""
    current = value
    for key in path:
        if current is None:
            return None
        if isinstance(key, int):
            if isinstance(current, (list, tuple)) and 0 <= key < len(current):
                current = current[key]
                continue
            return None
        if isinstance(current, dict):
            current = current.get(key)
            continue
        current = getattr(current, key, None)
    return current


class LLMBackend(ABC):
    """Abstract base class for LLM transport backends."""

    def __init__(self, api_base: str, api_key: str | None = None):
        self.api_base = api_base
        self.api_key = api_key
        self._client: Any = None

    @property
    def client(self) -> Any:
        """Lazily create and cache the transport client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def supports_thinking(self) -> bool:
        """Whether this backend can extract reasoning traces."""
        return False

    @abstractmethod
    def _create_client(self) -> Any:
        """Build the underlying SDK client."""

    @abstractmethod
    def request(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        stream: bool,
        think: ThinkValue,
    ) -> Any:
        """Send a chat request and return the raw response/stream."""

    @abstractmethod
    def extract_content(self, chunk: Any) -> str:
        """Extract text content from a single stream chunk."""

    @abstractmethod
    def extract_response(self, response: Any) -> str:
        """Extract text from a completed (non-streamed) response."""

    def extract_thinking(self, chunk: Any) -> str:
        """Extract reasoning text from a stream chunk."""
        return ""


def create_backend(
    api_base: str, api_key: str | None = None, *, prefer_ollama: bool = False
) -> LLMBackend:
    """Factory: create the appropriate backend for the given configuration."""
    if prefer_ollama:
        from .ollama_backend import OllamaBackend
        return OllamaBackend(api_base, api_key)
    from .openai_backend import OpenAIBackend
    return OpenAIBackend(api_base, api_key)
