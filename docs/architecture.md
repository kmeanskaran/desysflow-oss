# Architecture

## System Overview

DesysFlow consists of three primary layers:
- CLI orchestration (`desysflow_cli`)
- API service (`FastAPI`)
- UI workspace (`React + Vite`)

## Agent Graph Wiring (Base Flow)

`graph/workflow.py` compiles a linear `StateGraph` with these nodes:

1. `extract_requirements`
2. `select_template`
3. `generate_architecture`
4. `inject_edge_cases`
5. `select_primary_architecture`
6. `diagram_generator`
7. `diagram_quality_agent`
8. `report_generator`
9. `cloud_infra_agent`

This is the shared orchestration backbone used by CLI generation and API generation endpoints.

For the agent-by-agent view, see [Agentic Architecture](agentic-architecture.md).

## API-Orchestrated Extensions

`api/routes.py` layers additional flows around the base graph:

- Async operation tracking (`/design/async`, `/design/followup/async`)
  - streams node progress from `graph.stream(..., stream_mode="updates")`
  - exposes step-by-step progress for UI polling
- Follow-up flow (`/design/followup`, `/design/followup/async`)
  - merges session memory context
  - preserves diagram stability via Mermaid diff/stabilization
- Integrated critic/revision loop in the main workflow
  - generates critic findings
  - applies reviser updates
  - regenerates diagram/report/cloud outputs
- Cloud redesign (`/design/cloud-redesign`)
  - reruns diagram/report generation targeted to selected provider

## Key Modules

- `agents/`: generation and review agents
- `api/`: HTTP routes, async orchestration, critic/cloud endpoints
- `services/`: storage, session, LLM, guardrails
- `schemas/`: API contracts
- `graph/`: base orchestration graph
- `utils/`: parser, formatting, memory helpers
- `ui/`: frontend app

## Data Storage

Default local storage under `./.desysflow`:
- versioned design artifacts
- CLI/session databases (SQLite)
- UI conversation records
- session artifacts
