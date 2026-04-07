# CLI Guide

## Command Summary

```bash
desysflow design
desysflow redesign
```

Launcher shortcut:

```bash
./letsvibedesign cli
```

## `design`

Generate a versioned design package from current source.

```bash
desysflow design --source . --out ./desysflow --project desysflow-cli
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
- input mode (`vibe-now` or `ask`)

Choices use plain typed/numeric selection.

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
