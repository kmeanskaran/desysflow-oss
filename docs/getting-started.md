# Getting Started

## Prerequisites

- Python 3.11+
- `uv` installed and available in `PATH`
- Node.js and npm

## 1. Initial Setup

Install globally with the hosted installer:

```bash
curl -fsSL https://raw.githubusercontent.com/kmeanskaran/desysflow-oss/main/scripts/install.sh | bash
source ~/.bashrc    # or: source ~/.zshrc
letsvibedesign
```

Or run from a local clone:

```bash
LETSVIBEDESIGN_LOCAL_REPO="$PWD" LETSVIBEDESIGN_OFFLINE=1 ./scripts/install.sh
source ~/.bashrc    # or: source ~/.zshrc
letsvibedesign
```

Run the single bootstrap entrypoint:

```bash
letsvibedesign
```

This will:
- Create `.venv`
- Install Python dependencies
- Install UI dependencies
- Ask for model provider/model
- Write local `.env.example`
- Validate model availability

## 2. Run Modes

```bash
letsvibedesign          # CLI workflow
letsvibedesign studio   # API + UI
```

Notes:
- `letsvibedesign` runs the persistent CLI loop and returns to `letsdesign>` after each generation.
- `studio` runs both services and prints both URLs.

## 3. Backend and UI URLs

- API docs: `http://localhost:8000/docs`
- UI: `http://localhost:5173`

## 4. Basic CLI Usage

Guided:

```bash
letsvibedesign
```

The launcher stays open after each run and accepts:
- `Enter` or `run` to run again
- `design` to enter a prompt interactively
- `design <prompt>` to run directly with that prompt
- `bye` to exit

Direct:

```bash
desysflow design --source . --out ./.desysflow --project my-project
desysflow redesign --source . --out ./.desysflow --project my-project --focus "improve reliability"
```

## 5. Basic UI Usage

Start the UI with the API:

```bash
letsvibedesign studio
```

Then:
- Open `http://localhost:5173`.
- Configure the model from the gear icon.
- Click `Check status`.
- Enter a design prompt.
- Use follow-up prompts to refine the existing design.

## 6. Configuration

Environment variables are stored in local `.env.example`. Typical keys:
- `MODEL_PROVIDER`
- `OLLAMA_MODEL`
- `OLLAMA_TIMEOUT`
- `OLLAMA_NUM_PREDICT`
- `OPENAI_MODEL`
- `ANTHROPIC_MODEL`
- `GROQ_MODEL`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`
- `DESYSFLOW_STORAGE_ROOT`
- `LLM_GUARDRAIL` — set to `true` to enable secret-leak detection on LLM output

### Model Selection and Validation

- CLI interactive:
  - run `desysflow design` and choose provider/model
  - for OpenAI/Anthropic/Groq, provide API key when prompted
- CLI explicit flags:
  - `--model-provider`, `--model`, `--api-key`
- UI:
  - use the setup modal (gear icon) to set provider/model/API key
  - `Check status` performs a live provider check:
    - OpenAI/Anthropic/Groq: auth + endpoint probe
    - Ollama: local endpoint reachability + model presence

### Config File

Edit `desysflow.config.yml` in the project root to customize:
- Available role personas, languages, cloud targets, styles
- AI provider options and default models
- Default values for CLI prompts
