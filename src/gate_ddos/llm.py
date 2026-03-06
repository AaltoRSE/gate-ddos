import os
import time

from ollama import Client
from .constants import LLM_MAX_RETRIES, LLM_RETRY_DELAY, LLM_REASONING, LLM_STREAM

api_key = os.environ.get("OPENAI_API_KEY")
client = Client(
    host="http://localhost:11434",
    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
)


def generate(system_prompt: str, prompt: str, model: str) -> str:
    """Stream a chat completion from the LLM and return the full response."""
    if not prompt or not prompt.strip():
        raise ValueError("LLM prompt must not be empty")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    last_error: Exception | None = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            chunks: list[str] = []
            for part in client.chat(model=model, messages=messages, stream=LLM_STREAM, think=LLM_REASONING):
                if part.message.content:
                    print(part.message.content, end="", flush=True)
                    chunks.append(part.message.content)

            print("\n--- Done ---\n")
            result = "".join(chunks).strip()
            if not result:
                raise RuntimeError(
                    f"LLM returned an empty response for model '{model}'. "
                    "Check that the model is loaded and the prompt is valid."
                )
            return result

        except OSError as exc:
            last_error = exc
            if attempt < LLM_MAX_RETRIES:
                print(
                    f"\n  Connection error (attempt {attempt}/{LLM_MAX_RETRIES}): {exc}"
                    f"\n  Retrying in {LLM_RETRY_DELAY}s...\n"
                )
                time.sleep(LLM_RETRY_DELAY)

    raise ConnectionError(
        f"Failed to connect to LLM after {LLM_MAX_RETRIES} attempts. "
        f"Last error: {last_error}"
    )
