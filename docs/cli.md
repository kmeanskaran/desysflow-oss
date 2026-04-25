# CLI Guide

## Command Summary

```bash
desysflow design
desysflow redesign
```

Launcher shortcut:

```bash
letsvibedesign
```

`letsvibedesign` opens a persistent launcher loop. After each run it returns to a `letsvibe>` prompt instead of exiting immediately.

## `design`

Generate a versioned design package from current source.

```bash
desysflow design --source . --out ./.desysflow --project desysflow-cli
```

Non-interactive example:

```bash
desysflow design \
  --source . \
  --out ./.desysflow \
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
desysflow redesign --source . --out ./.desysflow --project desysflow-cli --focus "improve reliability"
```

## Interactive Prompts

When flags are omitted in an interactive terminal, CLI asks for:
- provider (`openai`, `anthropic`, `ollama`)
- model name
- API key (OpenAI/Anthropic only)
- language (`python`, `typescript`, `go`, `java`, `rust`)
- cloud target (`local`, `aws`, `gcp`, `azure`, `hybrid`)
- style (`minimal`, `balanced`, `detailed`)
- web-search mode (`auto`, `on`, `off`)
- role/persona
- input mode (`vibe-now` or `ask`) for non-empty repositories
- prompt text immediately for empty repositories
- optional prompt text for non-empty repositories when `ask` is selected, including when the repo has files but no existing `.desysflow` baseline

Choices use plain typed/numeric selection.

Repository-aware defaults:
- If the current repository contains source files, CLI detects the dominant language by file extension count and uses that as the default language.
- If the current repository is empty, CLI skips `Input mode` and directly asks for the product or feature prompt.
- If the current repository has files but no `.desysflow` baseline yet, CLI still offers `vibe-now` or `ask` and explains that `vibe-now` infers strictly from the current directory.
- If `--out` is omitted, CLI writes artifacts and local SQLite state under `./.desysflow`.

Launcher loop commands:
- `Enter` or `run`: run `desysflow design` again with normal interactive prompts
- `design`: ask for a prompt, then run `desysflow design --prompt "..."`
- `design <prompt>`: run directly with that prompt
- plain text: treat the text as a prompt and run design
- `bye`: exit the loop

Run output uses simple emoji-led lines:
- `🚀` for the run header
- stage headers like `🧭 Understand the request` and `🏗️ Draft the architecture`
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
- `.desysflow/<project>/latest`
- `.desysflow/<project>/vN/HLD.md`
- `.desysflow/<project>/vN/LLD.md`
- `.desysflow/<project>/vN/TECHNICAL_REPORT.md`
- `.desysflow/<project>/vN/NON_TECHNICAL_DOC.md`
- `.desysflow/<project>/vN/diagram.mmd`
- `.desysflow/<project>/vN/DIFF.md`
- `.desysflow/<project>/vN/METADATA.json`

Local storage files:
- `.desysflow/.desysflow_cli.db`
- `.desysflow/.desysflow_session.db`
- `.desysflow/session_artifacts/`
