import os
from typing import Any, cast

from openai import OpenAI

from .backend import LLMBackend, lookup_path


def _join_text_parts(content: list[Any]) -> str:
    """Join OpenAI content part arrays into plain text."""
    return "".join(
        str(item.get("text", "") or "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


class OpenAIBackend(LLMBackend):
    """OpenAI-compatible API backend (works with Ollama /v1, LiteLLM, vLLM, etc.)."""

    def _create_client(self) -> OpenAI:
        key = self.api_key or os.environ.get("OPENAI_API_KEY") or "not-required"
        return OpenAI(base_url=self.api_base, api_key=key)

    def request(self, model, messages, *, stream, think):
        return self.client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            stream=stream,
            extra_body={"think": think, "options": {"think": think}},
        )

    def extract_content(self, chunk):
        content = lookup_path(chunk, "choices", 0, "delta", "content")
        if isinstance(content, str):
            return content
        if isinstance(chunk, str):
            return chunk
        return ""

    def extract_response(self, response):
        content = lookup_path(response, "choices", 0, "message", "content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return _join_text_parts(content)
        return ""
