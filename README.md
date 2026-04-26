# DesysFlow OSS

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![npm](https://img.shields.io/badge/npm-9%2B-CB3837?logo=npm&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-%3E%3D0.2.0-1C3C3C)
![LangChain](https://img.shields.io/badge/LangChain-0.3%2B-1C3C3C)
![Ollama](https://img.shields.io/badge/Ollama-Supported-000000)
![OpenAI](https://img.shields.io/badge/OpenAI-Supported-412991?logo=openai&logoColor=white)
![Anthropic](https://img.shields.io/badge/Anthropic-Supported-191919)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-6%2B-646CFF?logo=vite&logoColor=white)

![DesysFlow Banner](assets/desysflow-banner.png)

DesysFlow OSS is a local-first, agentic system design platform that converts your codebase and product goals into versioned architecture artifacts. It provides a CLI for fast iteration, a local API backend, and a lightweight UI for guided design and refinement.

It includes:
- A simple CLI (`desysflow`) for local generation and refinement
- A local FastAPI backend
- A lightweight React UI for prompting and artifact inspection

## Why DesysFlow

- Local-first workflow with repo-native outputs
- Versioned design artifacts (`v1`, `v2`, ...)
- Structured outputs (HLD, LLD, technical report, non-technical brief, diagrams, diffs)
- Provider-flexible LLM support (`ollama`, `openai`, `anthropic`, `groq`)
- Optional secret-leak guardrail on LLM output
- Configurable via `desysflow.config.yml` (roles, languages, providers, defaults)

## Quick Start

### Prerequisites
- Python 3.11+
- `uv`
- Node.js + npm

### Choose an installation path

#### Option 1: Hosted installer and launcher

```bash
curl -fsSL https://raw.githubusercontent.com/kmeanskaran/desysflow-oss/main/scripts/install.sh | bash
source ~/.bashrc    # or: source ~/.zshrc
letsvibedesign
```

The installer is intended for macOS, Linux, and WSL2. It clones the repo into `~/.letsvibedesign/desysflow-oss`, bootstraps the local environment, and installs a global `letsvibedesign` launcher into `~/.local/bin`.

#### Option 2: Existing local checkout with the same launcher flow

```bash
LETSVIBEDESIGN_LOCAL_REPO="$PWD" LETSVIBEDESIGN_OFFLINE=1 ./scripts/install.sh
source ~/.bashrc    # or: source ~/.zshrc
letsvibedesign
```

#### Option 3: Direct CLI from this repo with `uv`

```bash
uv sync
uv run desysflow --help
```

Equivalent module form:

```bash
python -m desysflow_cli --help
```

#### Option 4: Install the CLI into your active Python environment

```bash
pip install -e .
desysflow --help
```

## Which command should you use?

- `letsvibedesign`: convenience launcher that bootstraps the repo, then opens the interactive CLI loop
- `letsvibedesign studio`: convenience launcher that starts the API and UI together
- `desysflow`: the actual CLI console script defined in `pyproject.toml`
- `python -m desysflow_cli`: module-based equivalent of `desysflow`

## CLI Usage

### Quick command map

```bash
letsvibedesign
letsvibedesign studio
uv run desysflow design --source .
python -m desysflow_cli design --source .
```

### Guided launcher mode

Run the basic guided CLI:

```bash
letsvibedesign
```

`letsvibedesign` stays open after each generation and shows a `letsdesign>` prompt.

Interactive prompt commands:
- `Enter` or `run`: run again with the current saved stack
- `design`: asks for a prompt, then continues with the current saved stack
- `design <prompt>`: run directly with that prompt
- `restart`: clear saved selections and start from scratch
- Any plain text: treated as a prompt and runs design
- `bye`: exit the CLI loop

### Direct CLI mode

Check the available commands:

```bash
desysflow --help
desysflow design --help
desysflow redesign --help
```

Run from this repo without installing a global command:

```bash
uv run desysflow design --source .
python -m desysflow_cli design --source .
```

Run directly with flags:

```bash
desysflow design --source . --out ./desysflow --project my-project
desysflow redesign --source . --out ./desysflow --project my-project --focus "improve scaling"
```

Run without prompts:

```bash
desysflow design \
  --source . \
  --out ./desysflow \
  --project my-project \
  --model-provider ollama \
  --model gpt-oss:20b-cloud \
  --language python \
  --cloud local \
  --style balanced \
  --no-interactive
```

Interactive defaults:
- Empty repositories immediately ask what you want to design.
- Non-empty repositories detect the dominant codebase language and use it as the default language selection.
- Non-empty repositories let you add an optional prompt, or press Enter to continue vibe designing from the current codebase or latest baseline.
- Generated artifacts and local session data are stored in `./desysflow` by default.

## UI Usage

Start API + UI together:

```bash
letsvibedesign studio
```

Open:
- UI: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

In the UI:
- Open model settings from the gear icon.
- Choose `ollama`, `openai`, `anthropic`, or `groq`.
- Enter the model name and API key when needed.
- Click `Check status`.
- Enter a design prompt, then use follow-up prompts to refine the result.

## Model Selection

- CLI:
  - interactive: `desysflow design` then follow prompts for provider/model/API key
  - non-interactive: `desysflow design --model-provider <provider> --model <name> [--api-key <key>]`
- UI:
  - open model settings (gear icon), choose provider/model, add API key for OpenAI/Anthropic/Groq
  - click `Check status` to run live connectivity/auth validation

Provider checks:
- OpenAI/Anthropic/Groq: verifies API key + endpoint reachability (`/models` probe)
- Ollama: verifies local endpoint reachability and that selected local model exists (`/api/tags`)

## Agentic Architecture

Primary LangGraph pipeline (`graph/workflow.py`):

1. `extract_requirements`
2. `select_template`
3. `generate_architecture`
4. `inject_edge_cases`
5. `critic_agent`
6. `revision_agent`
7. `diagram_generator`
8. `diagram_quality_agent`
9. `report_generator`
10. `cloud_infra_agent`

API also exposes additional loops on top of this base flow:
- async operation progress (`/design/async`, `/design/followup/async`)
- cloud redesign (`/design/cloud-redesign`: provider-specific diagram/report regeneration)

See [Agentic Architecture](docs/agentic-architecture.md) for more detail.

## Output Structure

DesysFlow writes versioned artifacts to `./desysflow/<project>/vN/` by default, including:
- `HLD.md`
- `LLD.md`
- `TECHNICAL_REPORT.md`
- `NON_TECHNICAL_DOC.md`
- `diagram.mmd`
- `SUMMARY.md`
- `CHANGELOG.md`
- `DIFF.md`
- `METADATA.json`

## Configuration

Edit `desysflow.config.yml` to customize roles, languages, cloud targets, providers, and defaults. The CLI and UI both read this file at startup.

For local Ollama runs, `OLLAMA_NUM_PREDICT` controls the maximum generated tokens. Lower it if generation looks slow on small local models.

## Guardrails

Set `LLM_GUARDRAIL=true` in `.env.example` to enable secret-leak detection on LLM output. The guardrail scans for API keys, tokens, database connection strings, and other credential patterns.

## Documentation

- [Getting Started](docs/getting-started.md)
- [CLI Guide](docs/cli.md)
- [Architecture](docs/architecture.md)
- [Agentic Architecture](docs/agentic-architecture.md)
- [Examples](docs/examples.md)
- [Project Overview](docs/project-overview.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Author

- X: [@kmeanskaran](https://x.com/kmeanskaran)
- Website: [kmeanskaran.com](https://kmeanskaran.com)

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
