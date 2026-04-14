# Project Overview

DesysFlow OSS is an open-source, local-first system design workspace focused on practical design generation from real codebases.

## Scope

Current scope includes:
- source-aware architecture generation
- versioned technical artifacts
- interactive CLI workflows for generation and refinement
- local UI for browsing and follow-up prompts
- async API operation tracking for UI progress
- local persistence for generated artifacts and UI conversations

## Design Principles

- Keep workflows local by default
- Produce deterministic, reviewable markdown outputs
- Preserve version history of architecture decisions
- Prefer practical implementation detail over abstract output

## Packaging

- Python package metadata in `pyproject.toml`
- CLI entrypoint: `python -m desysflow_cli`
- helper launcher: `letsvibedesign`
- launcher modes: `cli`, `dev`

## Configuration

DesysFlow uses a `desysflow.config.yml` file in the project root to control:
- Role personas (MLOps, DevOps, DevSecOps, etc.)
- Implementation languages
- Cloud deployment targets
- AI providers and their default models
- Default values for style, search mode, design mode

The CLI and API both read this config at startup.

## Agent Wiring Snapshot

Base graph order (`graph/workflow.py`):
`extract_requirements -> select_template -> generate_architecture -> inject_edge_cases -> select_primary_architecture -> diagram_generator -> diagram_quality_agent -> report_generator -> cloud_infra_agent`

API extends this with:
- async operation progress steps
- optional critic/reviser loop for existing sessions
- cloud-specific redesign endpoints

See [Agentic Architecture](agentic-architecture.md) for the detailed agent roles and extension points.

## Guardrails

DesysFlow includes an optional secret-leak guardrail (`services/guardrails.py`) that scans LLM output for leaked credentials, API keys, and other secrets. Enable it by setting:

```bash
LLM_GUARDRAIL=true
```

The local launcher and helper scripts read this from `.env.example`.
