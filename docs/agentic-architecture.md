# Agentic Architecture

DesysFlow uses a small agent graph to turn a prompt and source context into design artifacts. The same base graph powers CLI and API generation.

## Base Graph

`graph/workflow.py` wires the main LangGraph flow:

```text
extract_requirements
select_template
generate_architecture
inject_edge_cases
select_primary_architecture
diagram_generator
diagram_quality_agent
report_generator
cloud_infra_agent
```

## Agent Roles

- `extract_requirements`: extracts goals, constraints, scale hints, and system needs from the prompt.
- `select_template`: selects a base system design template.
- `generate_architecture`: produces the primary architecture proposal.
- `inject_edge_cases`: adds reliability, scaling, security, and failure-mode considerations.
- `select_primary_architecture`: normalizes the selected design path.
- `diagram_generator`: generates Mermaid architecture diagrams.
- `diagram_quality_agent`: checks diagram shape and repairs weak output.
- `report_generator`: generates structured HLD, LLD, and reports.
- `cloud_infra_agent`: maps the design to provider-specific infrastructure guidance.

## API Extensions

The API wraps the base graph with product workflows used by the UI:

- Async progress: `/design/async`, `/design/followup/async`, and `/operations/{operation_id}` expose running state to the UI.
- Follow-up refinement: `/design/followup` and `/design/followup/async` use session memory and stabilize Mermaid diagrams across iterations.
- Critic loop: built into the main workflow via `critic_agent` and `revision_agent` before diagram/report generation.
- Cloud redesign: `/design/cloud-redesign` remaps the latest design to a selected cloud provider.

## Persistence

Generated CLI artifacts are written under `./.desysflow/<project>/vN/` by default.

The UI/API stores conversation state locally through the conversation/session stores so users can reopen previous UI sessions.

## Guardrails

When `LLM_GUARDRAIL=true`, generated LLM output is scanned for likely secrets before it is returned or persisted.
