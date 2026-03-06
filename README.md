# Gate Distributed Document Oriented Solution

Fill a `.docx` template with LLM-generated content.

Write a DOCX file with `{{ KEY || prompt }}` placeholders. Point the tool at a system-prompt file and a model running in Ollama. It generates each section, renders the Markdown output as DOCX formatting (headings, lists, tables, bold) and saves the result.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | |
| [Ollama](https://ollama.com) | Running on `http://localhost:11434` |
| A model | Default: `qwen3.5:9b` Download: `ollama pull qwen3.5:9b` |

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
source .venv/bin/activate    # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Pull the default model
ollama pull qwen3.5:9b

# 4. Run
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.docx -o OUTPUT.docx
```

---

## Placeholders

Add these anywhere in a DOCX (paragraphs, table cells, headers, footers):

```text
{{ SUMMARY     || Give the project name as one sentence. }}
{{ DESCRIPTION || Describe the project goals in several sentences. }}
{{ FOOTER }}
```

| Format | Behaviour |
|---|---|
| `{{ KEY \|\| prompt }}` | Calls the LLM; output replaces the placeholder |
| `{{ KEY }}` | Lookup-only uses the JSON cache value; becomes empty if absent |

Rules:
- The same key with the same prompt reuses the first generated output everywhere.
- The same key with a **different** prompt raises an error.
- Placeholders can span multiple paragraphs.

---

## Options

```text
python gate-ddos.py SYSTEM_PROMPT.md TEMPLATE.docx [options]
```

| Option | Default | Description |
|---|---|---|
| `-o / --output PATH` | `<template>-new.docx` | Output file |
| `--model MODEL` | `qwen3.5:9b` | Ollama model |
| `--json PATH` | off | Cache file: reuse existing outputs, write new ones back |
| `--force` | off | Ignore JSON cache and regenerate all prompt sections |
| `--open-delim TEXT` | `{{` | Placeholder opening delimiter |
| `--close-delim TEXT` | `}}` | Placeholder closing delimiter |
| `--separator TEXT` | `\|\|` | Key / prompt separator |

### JSON cache

Pass `--json run-data.json` to cache generated sections. On the next run, sections already in the file are reused without calling the LLM. Missing sections are generated and merged back in.

```bash
# First run generates and saves
python gate-ddos.py SYSTEM.md TEMPLATE.docx --json cache.json

# Subsequent runs reuses cache, only generates new sections
python gate-ddos.py SYSTEM.md TEMPLATE.docx --json cache.json

# Force regeneration of all prompt sections
python gate-ddos.py SYSTEM.md TEMPLATE.docx --json cache.json --force
```

**Cache file format:**

```json
{
  "version": 1,
  "generatedAt": "2026-03-05T12:34:56.000000+00:00",
  "model": "qwen3.5:9b",
  "sections": {
    "SUMMARY": {
      "prompt": "Give the project name as one sentence.",
      "output": "Generated markdown here",
      "source": "llm"
    }
  }
}
```

Manual/static values can be provided with a flat shorthand:

```json
{ "FOOTER": "Internal use only" }
```

### Custom delimiters

```bash
python gate-ddos.py SYSTEM.md TEMPLATE.docx --open-delim "[[" --close-delim "]]" --separator "::"
```

Then use `[[ SUMMARY :: Write a short summary. ]]` in the DOCX.

### API gateway auth

If LLM sits behind a gateway that requires a token:

```bash
set OPENAI_API_KEY=your-token   # Windows
export OPENAI_API_KEY=your-token # macOS/Linux
```

---

## Code structure

```
gate-ddos.py                   Thin entry-point (sets up sys.path, calls main)
src/gate_ddos/
  cli.py                       Argument parsing and pipeline orchestration
  template_engine.py           Placeholder regex, parsing, and replacer factory
  section_store.py             In-memory cache, deduplication and prompt-mismatch detection
  json_cache.py                JSON cache read/write
  llm.py                       LLM streaming client
  models.py                    SectionRecord and TemplateSyntax dataclasses
  utils.py                     File reading and path validation
  constants.py                 Default model name and JSON schema version
  docx/
    __init__.py                Re-exports process_template_docx
    pipeline.py                DOCX traversal, placeholder replacement, Markdown->DOCX rendering
    styles.py                  Ensures required styles (headings, lists, tables) are present
    markdown.py                Markdown newline normalization for DOCX output
    html.py                    HTML post-processing (blockquotes, paragraph spacing)
```

---

## Run tests

```bash
python -m unittest discover -s tests
```
