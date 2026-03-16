import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .config import get_first_config_value, load_json_config
from .constants import LLM_MODEL, LLM_THINKING
from .docx import DocxPipeline
from .json_cache import read_json_store, write_json_store
from .llm.backend import create_backend
from .llm.generator import LLMGenerator
from .models import TemplateSyntax
from .text_pipeline import TextPipeline
from .ui import CliUI
from .utils import default_output_path, ensure_docx_path, read_text


def _config_bool(value, *, default: bool | None = None) -> bool | None:
    """Normalize config booleans while accepting common string values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Expected a boolean value in config, got {value!r}")


def parse_args(argv: list[str] | None = None):
    """Build and return the argument parser for the CLI."""
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config", help="Optional JSON config file path.")
    bootstrap_args, _ = bootstrap.parse_known_args(argv)
    config_path, config = load_json_config(bootstrap_args.config)

    default_model = get_first_config_value(config, ("model",), default=LLM_MODEL)
    default_backend = str(get_first_config_value(config, ("backend",), default="ollama")).strip().lower()
    default_api_base = get_first_config_value(config, ("apiBase",), ("api", "base"), default="http://localhost:11434/v1")
    default_api_key = get_first_config_value(config, ("apiKey",), ("api", "key"), default=os.environ.get("GATE_DDOS_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    default_json_path = get_first_config_value(config, ("json",), ("jsonCache",), ("cache", "path"), default=None)
    default_open_delim = get_first_config_value(config, ("openDelim",), ("syntax", "openDelim"), default="{{")
    default_close_delim = get_first_config_value(config, ("closeDelim",), ("syntax", "closeDelim"), default="}}")
    default_separator = get_first_config_value(config, ("separator",), ("syntax", "separator"), default="||")
    default_thinking = _config_bool(get_first_config_value(config, ("thinking",), ("llm", "thinking")), default=LLM_THINKING)
    default_force = _config_bool(get_first_config_value(config, ("force",), ("output", "force")), default=False)
    default_stream = _config_bool(get_first_config_value( config, ("llm", "stream"),), default=True)

    parser = argparse.ArgumentParser(description="Generate document output from {{ SECTION_KEY || prompt }} placeholders.")
    parser.add_argument("--config", default=config_path, help="Optional JSON config file path. If omitted, ./config.json is used when present.")
    parser.add_argument("system_prompt", help="Path to SYSTEM_PROMPT.md (or .txt)")
    parser.add_argument("template", help="Path to template file (.docx, .md, or .txt)")
    parser.add_argument("-o", "--output", help="Path for generated output (.docx, .md, or .txt)")
    parser.add_argument("--model", default=default_model, help=f"Model name (default: config or {LLM_MODEL})")
    parser.add_argument("--api-base", default=default_api_base, help="OpenAI-compatible base URL (default: config or http://localhost:11434/v1)")
    parser.add_argument("--api-key", default=default_api_key, help="Optional API key for OpenAI-compatible proxies (default: config or .env secret)")
    parser.add_argument("--json", default=default_json_path, help="Optional JSON file for debug/cache. If it exists, matching section outputs are reused. Missing sections are generated and then merged back into the file.")
    parser.add_argument("--open-delim", dest="open_delim", default=default_open_delim, help="Template placeholder opening delimiter (default: config or {{)")
    parser.add_argument("--close-delim", dest="close_delim", default=default_close_delim, help="Template placeholder closing delimiter (default: config or }})")
    parser.add_argument("--separator", dest="separator", default=default_separator, help="Template key/prompt separator inside placeholders (default: config or ||)")
    parser.add_argument("--backend", choices=("openai", "ollama"), default=default_backend, help="LLM backend transport (default: config or ollama)")

    thinking_group = parser.add_mutually_exclusive_group()
    thinking_group.add_argument("--thinking", dest="thinking", action="store_true", help="Enable model thinking/reasoning mode when supported.")
    thinking_group.add_argument("--no-thinking", dest="thinking", action="store_false", help="Disable model thinking/reasoning mode.")
    parser.set_defaults(thinking=default_thinking, stream=default_stream)

    force_group = parser.add_mutually_exclusive_group()
    force_group.add_argument("--force", dest="force", action="store_true", help="Regenerate prompt-based sections even if present in --json cache. Key-only placeholders still use JSON/manual values.")
    force_group.add_argument("--no-force", dest="force", action="store_false", help="Do not force regeneration of prompt-based sections.")
    parser.set_defaults(force=default_force)

    return parser.parse_args(argv)


class Application:
    """Orchestrates the full gate-ddos pipeline: read inputs, process template, write outputs."""

    def __init__(self, args):
        self.args = args

    def run(self) -> None:
        """Execute the full pipeline."""
        self._validate()

        self.syntax = TemplateSyntax(
            open_delim=self.args.open_delim,
            close_delim=self.args.close_delim,
            separator=self.args.separator,
        )
        self.store = read_json_store(self.args.json)
        self.system_prompt = read_text(self.args.system_prompt, "System prompt").strip()

        self.ui = self._create_ui()
        self.ui.configure_run(
            api_base=self._api_base,
            cache_path=self.args.json,
            thinking=self._thinking,
            stream=self._stream,
            force=self.args.force,
        )

        self.generator = self._create_generator()

        template_path = Path(self.args.template)
        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")

        output_path = self.args.output or default_output_path(self.args.template)
        template_suffix = self._validate_paths(template_path, output_path)

        output_dir = Path(output_path).parent
        if output_dir and not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)

        run_error = None
        try:
            self.ui.phase("Template processing", "Resolving placeholders, cache entries, and generated sections.")
            self._process(template_path, template_suffix, output_path, self._generate)
        except KeyboardInterrupt as exc:
            run_error = exc
        except Exception as exc:
            run_error = exc

        json_error = None
        try:
            if self.args.json:
                self.ui.phase("Persisting cache", f"Writing merged section cache to {Path(self.args.json).name}.")
            write_json_store(self.args.json, self.store, self.args.model)
        except Exception as exc:
            json_error = exc

        if run_error is None and json_error is None:
            self.ui.complete(output_path)
            return

        self.ui.close()
        _raise_run_failure(run_error, json_error)

    def _create_ui(self) -> CliUI:
        return CliUI(backend=self._backend, model=self.args.model, enabled=True)

    def _create_generator(self) -> LLMGenerator:
        backend = create_backend(self._api_base, self._api_key, prefer_ollama=self._backend == "ollama")
        return LLMGenerator(backend, self.args.model, enable_thinking=self._thinking, stream=self._stream, ui=self.ui)

    def _generate(self, system_prompt: str, prompt: str) -> str:
        return self.generator.generate(system_prompt, prompt)

    @property
    def _backend(self) -> str:
        return str(getattr(self.args, "backend", "ollama")).strip().lower()

    @property
    def _api_base(self) -> str:
        return getattr(self.args, "api_base", "http://localhost:11434/v1")

    @property
    def _api_key(self) -> str | None:
        return getattr(self.args, "api_key", None)

    @property
    def _thinking(self) -> bool:
        return getattr(self.args, "thinking", LLM_THINKING)

    @property
    def _stream(self) -> bool:
        return bool(getattr(self.args, "stream", True))

    def _validate(self) -> None:
        for attr, flag in (("open_delim", "--open-delim"), ("close_delim", "--close-delim"), ("separator", "--separator")):
            if not getattr(self.args, attr):
                raise ValueError(f"{flag} cannot be empty")
        if not self._api_base:
            raise ValueError("--api-base cannot be empty")

    @staticmethod
    def _validate_paths(template_path: Path, output_path: str) -> str:
        output_suffix = Path(output_path).suffix.lower()
        if output_suffix not in (".docx", ".md", ".txt"):
            raise ValueError("Output must be .docx, .md, or .txt")

        template_suffix = template_path.suffix.lower()
        if template_suffix == ".docx" and output_suffix != ".docx":
            raise ValueError("DOCX templates require .docx output")
        if template_suffix != ".docx" and output_suffix == ".docx":
            raise ValueError("Text templates (.md/.txt) cannot output .docx")
        return template_suffix

    def _create_pipeline(self, template_suffix: str, generate_fn, *, ui: CliUI | None):
        if template_suffix == ".docx":
            return DocxPipeline(
                system_prompt=self.system_prompt,
                syntax=self.syntax,
                store=self.store,
                generate=generate_fn,
                force=self.args.force,
                ui=ui,
            )
        return TextPipeline(
            system_prompt=self.system_prompt,
            syntax=self.syntax,
            store=self.store,
            generate=generate_fn,
            force=self.args.force,
            ui=ui,
        )

    def _process(self, template_path: Path, template_suffix: str, output_path: str, generate_fn):
        pipeline = self._create_pipeline(template_suffix, generate_fn, ui=self.ui)
        if template_suffix == ".docx":
            pipeline.process(ensure_docx_path(template_path, "Template"), output_path)
        else:
            pipeline.process(template_path, output_path)
        return pipeline


def _raise_run_failure(run_error: BaseException | None, json_error: Exception | None) -> None:
    """Raise the correct failure after attempting to persist the JSON cache."""
    if run_error and json_error:
        if isinstance(run_error, KeyboardInterrupt):
            raise RuntimeError(f"Generation interrupted. Also failed to write JSON: {json_error}") from run_error
        raise RuntimeError(f"Document generation failed: {run_error}. Also failed to write JSON: {json_error}") from run_error
    if run_error:
        raise run_error
    if json_error:
        raise json_error


def main():
    """Parse CLI arguments and run the tool."""
    load_dotenv()
    args = parse_args()
    app = Application(args)
    app.run()
