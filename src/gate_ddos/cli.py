import argparse
from pathlib import Path

from .constants import LLM_MODEL
from .docx import process_template_docx
from .utils import default_output_path, ensure_docx_path, read_text
from .json_cache import read_json_store, write_json_store
from .llm import generate
from .models import TemplateSyntax


def parse_args():
    """Build and return the argument parser for the CLI."""
    parser = argparse.ArgumentParser( description="Generate DOCX answers from {{ SECTION_KEY || prompt }} placeholders.")
    parser.add_argument("system_prompt", help="Path to SYSTEM_PROMPT.md (or .txt)")
    parser.add_argument("template", help="Path to template DOCX file")
    parser.add_argument("-o", "--output", help="Path for generated DOCX output")
    parser.add_argument("--model", default=LLM_MODEL, help=f"Ollama model (default: {LLM_MODEL})")
    parser.add_argument("--json", help="Optional JSON file for debug/cache. If it exists, matching section outputs are reused. Missing sections are generated and then merged back into the file.")
    parser.add_argument("--open-delim", dest="open_delim", default="{{", help="Template placeholder opening delimiter (default: {{)")
    parser.add_argument("--close-delim", dest="close_delim", default="}}", help="Template placeholder closing delimiter (default: }})")
    parser.add_argument("--separator", dest="separator", default="||", help="Template key/prompt separator inside placeholders (default: ||)")
    parser.add_argument("--force", action="store_true", help="Regenerate prompt-based sections even if present in --json cache Key-only placeholders still use JSON/manual values.")
    return parser.parse_args()


def run(args):
    """Execute the full pipeline: read inputs, process template, write outputs."""
    for attr, flag in (("open_delim", "--open"), ("close_delim", "--close"), ("separator", "--sep")):
        if not getattr(args, attr):
            raise ValueError(f"{flag} cannot be empty")

    syntax = TemplateSyntax(open_delim=args.open_delim, close_delim=args.close_delim, separator=args.separator)
    store = read_json_store(args.json)

    system_prompt = read_text(args.system_prompt, "System prompt").strip()
    template_path = ensure_docx_path(args.template, "Template")

    output_path = args.output or default_output_path(args.template)
    if Path(output_path).suffix.lower() != ".docx":
        raise ValueError("Output must be a .docx file")

    output_dir = Path(output_path).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    # Process the document, then always try to persist the cache-even on failure.
    doc_error = None
    try:
        process_template_docx(
            template_path=template_path,
            output_path=output_path,
            system_prompt=system_prompt,
            model=args.model,
            syntax=syntax,
            store=store,
            generate=generate,
            force=args.force,
        )
    except Exception as exc:
        doc_error = exc

    json_error = None
    try:
        write_json_store(args.json, store, args.model)
    except Exception as exc:
        json_error = exc

    if doc_error and json_error:
        raise RuntimeError(f"Document generation failed: {doc_error}. Also failed to write JSON: {json_error}")
    if doc_error:
        raise doc_error
    if json_error:
        raise json_error

    print(f"Saved: {output_path}")


def main():
    """Parse CLI arguments and run the tool."""
    args = parse_args()
    run(args)
