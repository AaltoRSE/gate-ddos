# Gate Distributed Document Oriented Solution

Standalone CLI tool for filling templates with LLM-generated content.

Use a template file with `{{ KEY || prompt }}` placeholders, a system-prompt file and an LLM endpoint. The tool fills the template once per section, can reuse cached results and writes the final content back into the output file.

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| Backend endpoint | Example: Ollama at `http://localhost:11434/v1` or an OpenAI-compatible `/v1` URL |
| A model | Default: `qwen3.5:9b` |

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up config and environment variables
cp config.example.json config.json
cp env.example .env

# 4. Pull the default model
ollama pull qwen3.5:9b

# 5. Run
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.docx -o OUTPUT.docx
```

## How it works

At a high level, the tool does this:

1. Load configuration, system prompt, template and optional JSON cache.
2. Find placeholders such as `{{ SUMMARY || Write a short summary. }}`.
3. For each placeholder, either reuse a cached section or call the LLM once.
4. Render the generated section text back into the target output format.
5. Persist the final section outputs back to the JSON cache.

This makes it useful when you want a structured draft from a fixed template instead of chatting section-by-section by hand.

## Template format

```text
{{ SUMMARY     || Give the project name as one sentence. }}
{{ DESCRIPTION || Describe the project goals in several sentences. }}
{{ FOOTER }}
```

| Format | Behaviour |
|---|---|
| `{{ KEY \|\| prompt }}` | Calls the LLM once; output replaces the placeholder |
| `{{ KEY }}` | Lookup-only uses the JSON cache value; becomes empty if absent |

Important behavior:
- The same key with the same prompt reuses the first generated output everywhere.
- If a cached key is run again with a different prompt on a later run, it is regenerated and the cache entry is updated.
- The same key with a different prompt in the same document raises a warning and leaves the conflicting placeholder unchanged.
- Placeholders can span multiple paragraphs.

## Common commands

DOCX output:

```bash
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.docx -o OUTPUT.docx
```

Markdown or text output:

```bash
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.md -o OUTPUT.md
```

Reuse cache:

```bash
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.docx --json cache.json
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.docx --json cache.json --force
```

See all available flags:

```bash
python gate-ddos.py --help
```

The CLI output is designed to be informative and user-friendly, with clear sections for configuration, generation progress and final output.

## Configuration

Configuration details in `config.example.json`, so that file should be the main reference.

In short:
- Use `config.json` for non-secret defaults.
- Use `.env` for secrets such as API keys.
- CLI flags override config values.

## JSON cache

Pass `--json run-data.json` to cache generated sections. On the next run, sections already in the file are reused without calling the LLM. Missing sections are generated and merged back in.

Output extension rules:

- `.docx` template requires `.docx` output.
- `.md`/`.txt` template requires `.md` or `.txt` output.

## Testing

Run the full test suite:

```bash
python -m unittest discover -s tests
```

Run a single test module:

```bash
python -m unittest tests.test_docx_pipeline
```

