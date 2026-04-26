# CLI Guide

## Command Summary

```bash
desysflow --help
desysflow design
desysflow redesign
```

Equivalent module entrypoint:

```bash
python -m desysflow_cli --help
python -m desysflow_cli design
```

Launcher shortcut:

```bash
letsvibedesign
```

`desysflow` is the package console script. `python -m desysflow_cli` runs the same CLI through the Python module. `letsvibedesign` is a convenience launcher that bootstraps the repo and opens a persistent loop.

If you are running from a local checkout without installing the package globally, use:

```bash
uv run desysflow design --source .
```

## `design`

Generate a versioned design package from current source.

```bash
desysflow design --source . --out ./desysflow --project desysflow-cli
```

Equivalent forms:

```bash
uv run desysflow design --source .
python -m desysflow_cli design --source .
```

Non-interactive example:

```bash
desysflow design \
  --source . \
  --out ./desysflow \
  --project desysflow-cli \
  --model-provider ollama \
  --model gpt-oss:20b-cloud \
  --language python \
  --cloud local \
  --style balanced \
  --no-interactive
```

## `redesign`

Compatibility alias for explicit refinement with focus.

```bash
desysflow redesign --source . --out ./desysflow --project desysflow-cli --focus "improve reliability"
```

Equivalent forms:

```bash
uv run desysflow redesign --source . --focus "improve reliability"
python -m desysflow_cli redesign --source . --focus "improve reliability"
```

## Interactive Prompts

When flags are omitted in an interactive terminal, CLI asks for:
- provider (`openai`, `anthropic`, `groq`, `ollama`)
- model name
- API key (OpenAI/Anthropic/Groq only)
- language (`python`, `typescript`, `go`, `java`, `rust`)
- cloud target (`local`, `aws`, `gcp`, `azure`, `hybrid`)
- style (`minimal`, `balanced`, `detailed`)
- web-search mode (`auto`, `on`, `off`)
- role/persona
- prompt text immediately for empty repositories
- optional prompt text for non-empty repositories, including when the repo already has an existing `desysflow` baseline

Choices use plain typed/numeric selection.
For Groq, the CLI can fetch the live model list and let you pick by number when `GROQ_API_KEY` is available.

Repository-aware defaults:
- If the current repository contains source files, CLI detects the dominant language by file extension count and uses that as the default language.
- If the current repository is empty, CLI directly asks for the product or feature prompt.
- If the current repository has files or an existing `desysflow` baseline, CLI lets you leave the prompt blank and continue from the current workspace context.
- If `--out` is omitted, CLI writes artifacts and local SQLite state under `./desysflow`.

Launcher loop commands:
- `Enter` or `run`: run `desysflow design` again with normal interactive prompts
- `design`: ask for a prompt, then run `desysflow design --prompt "..."`
- `design <prompt>`: run directly with that prompt
- plain text: treat the text as a prompt and run design
- `bye`: exit the loop

Run output uses simple emoji-led lines:
- `🚀` for the run header
- numbered stage headers like `Step 1/5 🧭 Understand the request` and `Step 3/5 🏗️ Design the solution`
- short progress notes under each stage
- `✅` for completion details
- `⚠️` and `💡` for warnings and operator guidance

You can also pass model settings explicitly:

```bash
desysflow design \
  --model-provider ollama \
  --model gpt-oss:20b-cloud
```

## Output and Persistence

CLI outputs:
- `desysflow/<project>/latest`
- `desysflow/<project>/vN/HLD.md`
- `desysflow/<project>/vN/LLD.md`
- `desysflow/<project>/vN/TECHNICAL_REPORT.md`
- `desysflow/<project>/vN/NON_TECHNICAL_DOC.md`
- `desysflow/<project>/vN/diagram.mmd`
- `desysflow/<project>/vN/DIFF.md`
- `desysflow/<project>/vN/METADATA.json`

Local storage files:
- `desysflow/.desysflow_cli.db`
- `desysflow/.desysflow_session.db`
- `desysflow/session_artifacts/`
