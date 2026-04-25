from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from services.storage_paths import get_storage_root
from services.llm import check_llm_status, get_llm_config, is_llm_limit_error, list_ollama_models
from graph.workflow import run_workflow_with_updates
from utils.design_doc import build_system_design_doc
from utils.non_technical_doc import build_non_technical_doc
from utils.workflow_contract import (
    DESIGN_NODE_TO_STAGE,
    DESIGN_PROGRESS_STEPS,
    FOLLOWUP_NODE_TO_STAGE,
    FOLLOWUP_PROGRESS_STEPS,
)

# Config loader
_CONFIG_CACHE: dict[str, Any] | None = None


def load_config() -> dict[str, Any]:
    """Load desysflow.config.yml from the project root. Cached after first read."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    config_path = Path(__file__).resolve().parent.parent / "desysflow.config.yml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
    else:
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def cfg_list(key: str, fallback: list[str]) -> list[str]:
    """Get a list from config, falling back to hardcoded default."""
    val = load_config().get(key)
    return list(val) if isinstance(val, list) and val else fallback


def cfg_defaults() -> dict[str, str]:
    """Get the defaults section from config."""
    return load_config().get("defaults", {})


def cfg_providers() -> list[dict[str, str]]:
    """Get the providers list from config."""
    val = load_config().get("providers")
    return list(val) if isinstance(val, list) and val else [
        {"id": "openai", "label": "GPT-lover", "default_model": "gpt-4o"},
        {"id": "anthropic", "label": "Claude-lover", "default_model": "claude-sonnet-4-20250514"},
        {"id": "ollama", "label": "Ollama-lover", "default_model": "gpt-oss:20b-cloud"},
    ]


def default_project_name(source: Path) -> str:
    """Resolve the project folder name for versioned design outputs."""
    configured = str(cfg_defaults().get("project", "")).strip()
    if configured:
        return configured
    return "desysflow-cli" if source.name == "desysflow-oss" else source.name


def default_output_root(base: Path | None = None) -> Path:
    """Use a hidden local storage root in the current workspace by default."""
    configured = os.getenv("DESYSFLOW_STORAGE_ROOT", "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        # Backward-compat: transparently migrate legacy ".desflow" root naming.
        if configured_path.name == ".desflow":
            return configured_path.with_name(".desysflow")
        return configured_path
    root = base or Path.cwd()
    hidden = root / ".desysflow"
    legacy_hidden = root / ".desflow"
    if hidden.exists():
        return hidden
    if legacy_hidden.exists():
        return hidden
    return hidden

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "desysflow",
}

MEANINGFUL_SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".cxx",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".mdown",
    ".mkd",
    ".markdown",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
    ".ts",
    ".tsx",
    ".zsh",
}
MEANINGFUL_SOURCE_FILENAMES = {
    "bashrc",
    "dockerfile",
    "makefile",
    "readme",
    "readme.md",
    "readme.mdown",
    "readme.mkd",
    "readme.markdown",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "typescript",
    ".jsx": "typescript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
}

# Secret detection patterns — matched case-insensitively across all generated docs
SECRET_PATTERNS = [
    # Generic credentials
    (r'(?i)\b(password|passwd|pwd|secret|token|api.?key|apikey)\s*[:=]\s*["\']?[\w\-\.%/@]{4,}["\']?', 0),
    # Connection strings with embedded secrets
    (r'(?i)(mongodb|postgres|mysql|redis|amqp|mssql|oracle):\/\/[^@\s]+:[^@\s]+@', 0),
    # AWS / GCP / Azure tokens and keys
    (r'(?i)\b(AKIA|ABIA|ACMA|ASIA)[0-9A-Z]{16}', 0),
    (r'(?i)aws[_\-]?(access[_\-]?key[_\-]?id)\s*[:=]\s*\S+', 0),
    (r'(?i)aws[_\-]?(secret[_\-]?access[_\-]?key)\s*[:=]\s*\S+', 0),
    (r'(?i)amqp[_\-]?(login|password)\s*[:=]\s*\S+', 0),
    (r'(?i)(gcp|google)[_\-]?(api[_\-]?key|service[_\-]?account)\s*[:=]\s*\S+', 0),
    (r'(?i)azure[_\-]?(subscription|tenant|client)[_\-]?(id|key)\s*[:=]\s*\S+', 0),
    (r'(?i)sk_[a-zA-Z0-9]{20,}', 0),                           # OpenAI / most LLM keys
    (r'(?i)sk-ant-[a-zA-Z0-9]{20,}', 0),                       # Anthropic keys
    (r'(?i)ollama[_\-]?(api[_\-]?key)\s*[:=]\s*\S+', 0),
    # Bearer / Authorization tokens
    (r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{16,}', 0),
    (r'(?i)authorization\s*[:=]\s*(Bearer |Basic )[^"\s]{4,}', 0),
    # Private keys
    (r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----', 0),
    # Slack / GitHub tokens
    (r'(?i)(slack|github)[_\-]?(token|key|secret)\s*[:=]\s*\S+', 0),
    # Environment variable exports with values
    (r'(?i)export\s+(OPENAI_|ANTHROPIC_|AWS_|AZURE_|GCP_|SECRET_|TOKEN_|API_KEY|PASSWORD)', 0),
]
TOP_FILE_LIMIT = 60
REVIEW_LOOP_LIMIT = 2
BASELINE_CONTEXT_FILES = [
    "SUMMARY.md",
    "HLD.md",
    "LLD.md",
    "TECHNICAL_REPORT.md",
    "NON_TECHNICAL_DOC.md",
]
BASELINE_EXCERPT_LIMIT = 900

LOG_EMOJI = {
    "run": "🚀",
    "cmd": "🧭",
    "params": "🧩",
    "stage": "📍",
    "status": "•",
    "done": "✅",
    "warn": "⚠️",
    "hint": "💡",
}

STAGE_EMOJI = {
    "scope": "🧭",
    "context": "🧭",
    "extract": "🔎",
    "update": "🔄",
    "draft": "🏗️",
    "review": "🧪",
    "package": "📦",
    "write artifacts": "💾",
    "update local session db": "🗂️",
}

STAGE_TITLES = {
    "scope": "Understand the request",
    "context": "Load the current design",
    "extract": "Inspect the codebase",
    "update": "Refresh requirements and trade-offs",
    "draft": "Draft the architecture",
    "review": "Review and refine",
    "package": "Build the deliverables",
    "write artifacts": "Write files",
    "update local session db": "Save session history",
}


def log_line(kind: str, message: str) -> None:
    emoji = LOG_EMOJI.get(kind, "•")
    if kind == "stage":
        print("")
    print(f"{emoji} {message}")


def _stage_line(stage_key: str, fallback_label: str) -> None:
    emoji = STAGE_EMOJI.get(stage_key, "📍")
    title = STAGE_TITLES.get(stage_key, fallback_label)
    log_line("stage", f"{emoji} {title}")


def _truncate_cli_text(text: str, limit: int = 120) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _truncate_for_prompt(text: str, limit: int = BASELINE_EXCERPT_LIMIT) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


HLD_REQUIRED_SECTIONS = [
    "## Overview",
    "## Components",
    "## Data Flow",
    "## Scaling and Availability",
    "## Trade-offs",
    "## Future Improvements",
]
LLD_REQUIRED_SECTIONS = [
    "## APIs",
    "## Schemas",
    "## Service Communication",
    "## Caching",
    "## Error Handling",
    "## Deployment",
    "## Security",
    "## Future Improvements",
]
TECH_REPORT_REQUIRED_SECTIONS = [
    "## Sub-agent Topology",
    "## Parallel Execution Plan",
    "## Internal Reviewer Loop",
    "## Context Bloat Fixes",
    "## Session Management and Memory",
    "## Future Improvements",
]
NON_TECH_REQUIRED_SECTIONS = [
    "## Product Summary",
    "## Business Value",
    "## Target Users",
    "## Delivery Shape",
    "## Future Improvements",
]


@dataclass
class RunConfig:
    command: str
    source: Path
    output_root: Path
    project: str
    language: str
    style: str
    cloud: str
    web_search: str
    mode: str
    effective_mode: str
    focus: str
    role: str
    prompt: str
    non_interactive: bool
    model_provider: str = ""   # openai | anthropic | ollama
    model_name: str = ""       # provider-specific model name
    api_key: str = ""           # for openai / anthropic
    base_url: str = ""


@dataclass
class AnalysisContext:
    inventory: dict[str, Any]
    stack: dict[str, Any]
    module_map: dict[str, str]
    key_paths: list[str]
    web_enabled: bool
    references: list[dict[str, str]]
    latest_design: DesignBaseline | None


@dataclass
class ChatConfig:
    source: Path
    output_root: Path
    project: str
    session_id: str


@dataclass
class HistoryConfig:
    output_root: Path
    limit: int


@dataclass
class SourceCheckpoints:
    has_meaningful_files: bool
    inferred_language: str
    has_existing_design: bool
    latest_design_version: str


@dataclass
class DesignBaseline:
    version: str
    path: Path
    files: list[str]
    excerpts: dict[str, str]


# ----------------------------------------------------------------------
# Help formatter — sorts flags alphabetically within each group
# ----------------------------------------------------------------------
class _SortedHelpFormatter(argparse.HelpFormatter):
    def add_arguments(self, actions):
        actions.sort(key=lambda a: (a.option_strings or [a.dest])[0])
        super().add_arguments(actions)


# ----------------------------------------------------------------------
# Model resolution helpers
# ----------------------------------------------------------------------
def _provider_defaults() -> dict[str, dict[str, str]]:
    """Build provider → default model mapping from config."""
    result: dict[str, dict[str, str]] = {}
    for p in cfg_providers():
        result[p["id"]] = {"model": p.get("default_model", "")}
    return result


def _prompt_provider(default: str = "") -> str:
    providers = cfg_providers()
    print("")
    default_idx = None
    for i, p in enumerate(providers, 1):
        if p["id"] == default:
            default_idx = i
        print(f"  {i}) {p['label']}  ({p.get('desc', p['id'])})")
    while True:
        suffix = f" default: {default_idx}" if default_idx is not None else ""
        r = input(f"Select provider [1-{len(providers)}]{suffix}: ").strip()
        if not r and default_idx is not None:
            return default
        try:
            idx = int(r) - 1
            if 0 <= idx < len(providers):
                return providers[idx]["id"]
        except ValueError:
            pass
        print(f"  Invalid. Enter 1-{len(providers)}.")


def _prompt_model(provider: str, installed: list[str], default: str = "") -> str:
    default = default or _provider_defaults().get(provider, {}).get("model", "")
    if provider == "ollama":
        print("  Model name")
        if default:
            print(f"  Default: {default}")
        print("  Enter your installed Ollama model name.")
    placeholder = f" [{default}]" if default else ""
    name = input(f"  >{placeholder} ").strip()
    return name or default


def _confirm_choice(prompt: str, default: str = "n") -> bool:
    suffix = "[Y/n]" if default.lower() == "y" else "[y/N]"
    raw = input(f"{prompt} {suffix}: ").strip().lower()
    if not raw:
        return default.lower() == "y"
    return raw in ("y", "yes")


def _resolve_ollama_model_selection(
    installed: list[str],
    base_url: str,
    default: str = "",
) -> str:
    while True:
        model = _prompt_model("ollama", installed, default)
        if not model:
            print("  Model name is required for Ollama.")
            print("")
            continue
        if model in installed:
            return model

        print("")
        print(f"  '{model}' is not installed in Ollama at {base_url}.")
        print(f"  Download it with: ollama pull {model}")
        print("")
        if _confirm_choice("  Choose a different model?", default="y"):
            default = model
            print("")
            continue
        raise SystemExit("Aborted.")


def _is_meaningful_source_file(path: Path) -> bool:
    name = path.name.lower()
    if name in MEANINGFUL_SOURCE_FILENAMES:
        return True
    return path.suffix.lower() in MEANINGFUL_SOURCE_SUFFIXES


def _prompt_api_key(provider: str, current: str = "") -> str:
    prompt = f"  API key for {provider}"
    if current:
        prompt += " (press Enter to keep existing)"
    prompt += ": "
    value = input(prompt).strip()
    return value or current


def resolve_model(cfg: RunConfig) -> RunConfig:
    """Resolve provider → model name → API key from CLI flag → env var → interactive prompt."""
    interactive = (not cfg.non_interactive) and os.isatty(0)
    model_flags_supplied = any(
        [
            cfg.model_provider.strip(),
            cfg.model_name.strip(),
            cfg.api_key.strip(),
            cfg.base_url.strip(),
        ]
    )

    env_provider = os.getenv("MODEL_PROVIDER", "").strip()
    provider = cfg.model_provider or env_provider

    # Interactive runs should ask which provider/model to use unless explicit CLI flags were provided.
    if interactive and not model_flags_supplied:
        provider = _prompt_provider(provider or "ollama")
    if not provider:
        provider = "ollama"
    provider = provider.lower()
    if provider not in ("openai", "anthropic", "ollama"):
        provider = "ollama"

    # 2. API key: CLI flag → env var → prompt (openai/anthropic only)
    env_key = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
    api_key = cfg.api_key or os.getenv(env_key, "").strip()
    if provider != "ollama" and interactive and not model_flags_supplied:
        api_key = _prompt_api_key(provider, api_key)
    elif provider != "ollama" and not api_key and interactive:
        api_key = _prompt_api_key(provider)
    if api_key:
        os.environ[env_key] = api_key

    # 3. Base URL: CLI flag → env var → provider default
    base_url_env_key = "OPENAI_BASE_URL" if provider == "openai" else ("ANTHROPIC_BASE_URL" if provider == "anthropic" else "OLLAMA_BASE_URL")
    base_url_default = (
        "https://api.openai.com/v1" if provider == "openai"
        else "https://api.anthropic.com" if provider == "anthropic"
        else "http://localhost:11434"
    )
    base_url = cfg.base_url or os.getenv(base_url_env_key, "").strip() or base_url_default
    os.environ[base_url_env_key] = base_url

    # 4. Model name: CLI flag → env var → prompt → default
    installed: list[str] = []
    if provider == "ollama":
        installed = list_ollama_models(base_url)

    env_model_key = "OPENAI_MODEL" if provider == "openai" else ("ANTHROPIC_MODEL" if provider == "anthropic" else "OLLAMA_MODEL")
    model = cfg.model_name or os.getenv(env_model_key, "").strip()
    if provider == "ollama" and interactive:
        prompt_default = model or _provider_defaults().get(provider, {}).get("model", "")
        if not model_flags_supplied or not model:
            model = _resolve_ollama_model_selection(installed, base_url, prompt_default)
    elif interactive and not model_flags_supplied:
        model = _prompt_model(provider, installed, model)
    elif not model and interactive:
        model = _prompt_model(provider, installed)
    if not model:
        model = _provider_defaults().get(provider, {}).get("model", "")

    # Ollama validation
    if provider == "ollama" and model and model not in installed:
        if interactive:
            print("")
            print(f"  '{model}' is not installed in Ollama at {base_url}.")
            print(f"  Download it with: ollama pull {model}")
            print("")
            if _confirm_choice("  Choose a different model?", default="y"):
                model = _resolve_ollama_model_selection(installed, base_url, model)
            else:
                raise SystemExit("Aborted.")
        else:
            print(f"  [WARNING] '{model}' is not installed in Ollama at {base_url}.")
            print(f"  Install it with: ollama pull {model}")

    os.environ["MODEL_PROVIDER"] = provider
    os.environ[env_model_key] = model

    cfg.model_provider = provider
    cfg.model_name = model
    cfg.api_key = api_key
    cfg.base_url = base_url
    return cfg


def finalize_options(cfg: RunConfig) -> RunConfig:
    interactive = (not cfg.non_interactive) and os.isatty(0)

    cfg = resolve_model(cfg)

    if interactive:
        print(f"  Provider : {cfg.model_provider}")
        print(f"  Model    : {cfg.model_name}")
        print(f"  API key  : {'[set]' if cfg.api_key else '[none]'}")
        print("")

    language_choices = cfg_list("languages", ["python", "typescript", "go", "java", "rust"])
    source_checkpoints = collect_source_checkpoints(
        cfg.source,
        language_choices,
        output_root=cfg.output_root,
        project=cfg.project,
    )
    source_has_files = source_checkpoints.has_meaningful_files
    has_existing_design = source_checkpoints.has_existing_design

    defaults = cfg_defaults()
    language = cfg.language or os.getenv("DESYSFLOW_LANGUAGE", "").strip() or defaults.get("language", "python")
    style    = cfg.style    or os.getenv("DESYSFLOW_STYLE", "").strip()    or defaults.get("style", "balanced")
    cloud    = cfg.cloud    or os.getenv("DESYSFLOW_CLOUD", "").strip()    or defaults.get("cloud", "local")
    web      = cfg.web_search or os.getenv("DESYSFLOW_WEB_SEARCH", "").strip() or defaults.get("search_mode", "auto")
    mode     = cfg.mode     or os.getenv("DESYSFLOW_MODE", "").strip()     or defaults.get("design_mode", "smart")
    role     = cfg.role     or os.getenv("DESYSFLOW_ROLE", "").strip()     or defaults.get("role", "DevOps")
    prompt   = cfg.prompt.strip()

    if interactive:
        if source_has_files and not cfg.language and not os.getenv("DESYSFLOW_LANGUAGE", "").strip() and source_checkpoints.inferred_language:
            language = source_checkpoints.inferred_language
            print(f"  Checkpoint: dominant repository language detected -> {language}")
        language = _ask_choice("Implementation language", language_choices, language)
        style    = _ask_choice("Report style",          cfg_list("styles", ["balanced", "minimal", "detailed"]),          style)
        cloud    = _ask_choice("Cloud target",          cfg_list("clouds", ["local", "aws", "gcp", "azure", "hybrid"]),   cloud)
        web      = _ask_choice("Web search mode",       cfg_list("search_modes", ["auto", "on", "off"]),                   web)
        role     = _ask_choice("Role",                  cfg_list("roles", ["DevOps", "Principal Architect", "MLOps / AIOps"]), role)
        if cfg.command == "/design" and has_existing_design:
            mode = _ask_choice("Design routing",       cfg_list("design_modes", ["smart", "fresh", "refine"]),            mode)
        print("")
        prompt, _ = _collect_prompt_text(
            source_has_files=source_has_files,
            has_existing_design=has_existing_design,
            latest_design_version=source_checkpoints.latest_design_version,
            prompt=prompt,
        )

    focus = cfg.focus.strip() or prompt
    effective_mode = resolve_effective_mode(cfg.command, mode, has_existing_design, focus)

    return RunConfig(
        command=cfg.command,
        source=cfg.source,
        output_root=cfg.output_root,
        project=cfg.project,
        language=language,
        style=style,
        cloud=cloud,
        web_search=web,
        mode=mode,
        effective_mode=effective_mode,
        focus=focus,
        role=role,
        prompt=prompt,
        non_interactive=cfg.non_interactive,
        model_provider=cfg.model_provider,
        model_name=cfg.model_name,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    )


def _normalize_choice(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _ask_choice(label: str, values: list[str], default: str) -> str:
    print(f"  {label} (default: {default})")
    for idx, item in enumerate(values, 1):
        print(f"    {idx}) {item}")
    raw = input("  > ").strip()
    if not raw:
        return default

    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(values):
            return values[idx]

    normalized_map = {_normalize_choice(item): item for item in values}
    key = _normalize_choice(raw)
    if key in normalized_map:
        return normalized_map[key]

    for item in values:
        item_key = _normalize_choice(item)
        if key and (item_key.startswith(key) or key in item_key):
            return item
    return default


def ask_option(label: str, values: list[str], default: str) -> str:
    return _ask_choice(label, values, default)


def _collect_prompt_text(
    *,
    source_has_files: bool,
    has_existing_design: bool,
    latest_design_version: str = "",
    prompt: str = "",
) -> tuple[str, str]:
    prompt_text = prompt.strip()

    if source_has_files:
        if has_existing_design:
            label = latest_design_version or "latest"
            print(f"  Found existing .desysflow baseline ({label}).")
        else:
            print("  No existing .desysflow baseline was found for this repository.")
            print("  Choose 'vibe-now' to infer from the current directory only.")
            print("  Choose 'ask' to provide an explicit feature/change request.")

        input_mode = _ask_choice("Input mode", ["vibe-now", "ask"], "vibe-now")
        print("")
        if input_mode == "ask":
            print("  Prompt")
            if has_existing_design:
                print("  Describe the feature/change request for this codebase.")
            else:
                print("  Describe the feature/change request for the current codebase.")
            entered_prompt = input("  > ").strip()
            if entered_prompt:
                prompt_text = entered_prompt
        return prompt_text, input_mode

    if has_existing_design:
        label = latest_design_version or "latest"
        print(f"  Found existing .desysflow baseline ({label}).")
        return prompt_text, "vibe-now"

    print("  Prompt")
    print("  No code, shell, or markdown files were found in this repository.")
    print("  Describe the product/feature you want to design from scratch.")
    entered_prompt = input("  > ").strip()
    return (entered_prompt or prompt_text), "ask"


def print_main_help() -> None:
    print("DesysFlow CLI")
    print("")
    print("Usage:")
    print("  desysflow design [options]")
    print("  desysflow redesign [options]")
    print("")
    print("Commands:")
    print("  design     Generate a new versioned design package")
    print("  redesign   Refine from latest version (falls back to fresh when needed)")
    print("  help       Show this help")
    print("")
    print("Run 'desysflow design --help' or 'desysflow <command> --help' for detailed options.")
    print("")


def parse_run_args(command: str, argv: list[str] | None = None) -> RunConfig:
    parser = argparse.ArgumentParser(
        prog=f"desysflow {command.lstrip('/')}",
        description=(
            "Generate a versioned system-design package from a source repository."
            if command in {"/design", "design"}
            else "Refine from the latest generated design package."
        ),
        add_help=False,
        formatter_class=_SortedHelpFormatter,
    )

    provider_ids = [p["id"] for p in cfg_providers()]

    g = parser.add_argument_group("model options").add_argument
    g("--model-provider", metavar="PROVIDER",
      choices=provider_ids,
      help=f"LLM provider: {' | '.join(provider_ids)}  (default: prompted interactively)")
    g("--model", metavar="NAME",
      help="Model name, e.g. gpt-4o | claude-sonnet-4-20250514 | llama3  (default: prompted)")
    g("--api-key", metavar="KEY",
      help="API key for OpenAI or Anthropic  (prompted if not set)")
    g = parser.add_argument_group("project options").add_argument
    g("--source", default=".", metavar="PATH",
      help="Source repository to analyze (default: .)")
    g("--out", default="", metavar="PATH",
      help="Output root directory (default: ./.desysflow in the current working directory)")
    g("--project", default="", metavar="NAME",
      help="Project name (default: source directory name)")

    g = parser.add_argument_group("design options").add_argument
    g("--language", choices=cfg_list("languages", ["python", "typescript", "go", "java", "rust"]),
      help="Preferred implementation language")
    g("--style", choices=cfg_list("styles", ["minimal", "balanced", "detailed"]),
      help="Report depth style")
    g("--cloud", choices=cfg_list("clouds", ["local", "aws", "gcp", "azure", "hybrid"]),
      help="Cloud deployment target")
    g("--web-search", choices=cfg_list("search_modes", ["auto", "on", "off"]),
      help="External web search mode")
    g("--focus", default="", metavar="TEXT",
      help="Refinement goal for refine runs")
    g("--prompt", default="", metavar="TEXT",
      help="Design prompt (optional). If omitted, CLI generates from current codebase context.")
    g("--role", default="", metavar="NAME",
      help="Design role/persona, e.g. DevOps, Principal Architect")
    g("--mode", choices=cfg_list("design_modes", ["smart", "fresh", "refine"]),
      help="Routing mode: smart picks fresh or refine automatically")

    g = parser.add_argument_group("runtime options").add_argument
    g("--no-interactive", action="store_true",
      help="Skip all interactive prompts; use only CLI flags and env vars")

    parser.add_argument("--help", action="help",
      help="Show this help message and exit")

    ns = parser.parse_args(argv)

    source = Path(ns.source).expanduser().resolve()
    project = ns.project.strip() or default_project_name(source)

    cfg = RunConfig(
        command=command,
        source=source,
        output_root=Path(ns.out).expanduser().resolve() if ns.out.strip() else default_output_root().resolve(),
        project=project,
        language=(ns.language or "").strip(),
        style=(ns.style or "").strip(),
        cloud=(ns.cloud or "").strip(),
        web_search=(ns.web_search or "").strip(),
        mode=(ns.mode or "").strip(),
        effective_mode="",
        focus=ns.focus.strip(),
        role=(ns.role or "").strip(),
        prompt=(ns.prompt or "").strip(),
        non_interactive=bool(ns.no_interactive),
    )
    cfg.model_provider = (ns.model_provider or "").strip()
    cfg.model_name     = (ns.model or "").strip()
    cfg.api_key        = (ns.api_key or "").strip()
    return finalize_options(cfg)


def parse_chat_args(argv: list[str] | None = None) -> ChatConfig:
    parser = argparse.ArgumentParser(
        prog="desysflow chat",
        description="Compatibility alias for a single DesysFlow design generation.",
    )
    parser.add_argument("--source", default=".", help="Source repository path to analyze.")
    parser.add_argument("--out", default="", help="Storage root for local sessions and outputs.")
    parser.add_argument("--project", default="", help="Project name override.")
    parser.add_argument("--session", default="", help=argparse.SUPPRESS)
    ns = parser.parse_args(argv)
    source = Path(ns.source).expanduser().resolve()
    output_root = Path(ns.out).expanduser().resolve() if ns.out.strip() else default_output_root().resolve()
    project = ns.project.strip() or default_project_name(source)
    return ChatConfig(source=source, output_root=output_root, project=project, session_id=ns.session.strip())


def parse_history_args(argv: list[str] | None = None) -> HistoryConfig:
    parser = argparse.ArgumentParser(
        prog="desysflow history",
        description="List local DesysFlow chat sessions.",
    )
    parser.add_argument("--out", default="", help="Storage root for local sessions and outputs.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of sessions to show.")
    ns = parser.parse_args(argv)
    output_root = Path(ns.out).expanduser().resolve() if ns.out.strip() else default_output_root().resolve()
    return HistoryConfig(output_root=output_root, limit=max(1, ns.limit))


def normalize_cloud(value: str) -> str:
    return "local" if value == "none" else value


_REDACT_COUNTER = 0


def _next_redact_id() -> str:
    global _REDACT_COUNTER
    _REDACT_COUNTER += 1
    return f"REDACTED-{_REDACT_COUNTER}"


def scrub_secrets(text: str) -> tuple[str, list[str]]:
    """Replace secret-like values with [REDACTED-N] placeholders.

    Returns (scrubbed_text, list_of_redacted_labels).
    """
    global _REDACT_COUNTER
    redacted: list[str] = []
    for pattern, _ in SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            label = _next_redact_id()
            redacted.append(f"[{label}] {match.group().strip()}")
            text = text[:match.start()] + f"[{label}]" + text[match.end():]
    return text, redacted


def check_source_for_secrets(source: Path) -> list[str]:
    """Quick pre-scan of source files for high-confidence secret leaks.

    Scans only the first 20 lines of each file to avoid heavy I/O.
    Returns a list of warning messages for files that appear to contain secrets.
    """
    warnings: list[str] = []
    scan_count = 0
    for root, dirs, names in os.walk(source):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if scan_count >= 500:
                return warnings
            path = Path(root) / name
            if path.name.startswith("."):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]
            except Exception:
                continue
            joined = "\n".join(lines)
            for pattern, _ in SECRET_PATTERNS:
                if re.search(pattern, joined):
                    warnings.append(f"  {path}: possible secret pattern detected — review before sharing generated docs")
                    break
            scan_count += 1
    return warnings


def has_meaningful_source_files(source: Path) -> bool:
    """Return True when source has at least one code, shell, or markdown file."""
    for root, dirs, names in os.walk(source):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in names:
            if name.startswith("."):
                continue
            path = Path(root) / name
            if path.is_file() and _is_meaningful_source_file(path):
                return True
    return False


def infer_dominant_language(source: Path, allowed_languages: list[str]) -> str:
    allowed = {item.lower() for item in allowed_languages}
    # Preserve caller preference order, but compare case-insensitively.
    allowed_order: dict[str, int] = {}
    for idx, item in enumerate(allowed_languages):
        key = item.lower()
        if key not in allowed_order:
            allowed_order[key] = idx
    counts: dict[str, int] = {}

    for root, dirs, names in os.walk(source):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in names:
            if name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            language = LANGUAGE_BY_SUFFIX.get(suffix, "")
            if not language or language not in allowed:
                continue
            counts[language] = counts.get(language, 0) + 1

    if not counts:
        return ""

    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], allowed_order.get(item[0], len(allowed_order))),
    )
    return ranked[0][0]


def resolve_latest_design_baseline(output_root: Path, project: str) -> DesignBaseline | None:
    project_root = output_root / project
    if not project_root.exists():
        return None

    latest_version = ""
    latest_path: Path | None = None
    latest_file = project_root / "latest"
    if latest_file.exists():
        latest_version = latest_file.read_text(encoding="utf-8", errors="ignore").strip()
        if latest_version:
            candidate = project_root / latest_version
            if candidate.exists() and candidate.is_dir():
                latest_path = candidate

    if latest_path is None:
        versions: list[tuple[int, Path]] = []
        for child in project_root.iterdir():
            if not child.is_dir() or not child.name.startswith("v"):
                continue
            try:
                versions.append((int(child.name[1:]), child))
            except ValueError:
                continue
        if versions:
            versions.sort()
            latest_number, latest_path = versions[-1]
            latest_version = f"v{latest_number}"

    if latest_path is None:
        return None

    excerpts: dict[str, str] = {}
    files: list[str] = []
    for name in BASELINE_CONTEXT_FILES:
        path = latest_path / name
        if not path.exists() or not path.is_file():
            continue
        content = read_text_or_empty(path)
        if not content.strip():
            continue
        files.append(name)
        excerpts[name] = _truncate_for_prompt(content)

    return DesignBaseline(
        version=latest_version or latest_path.name,
        path=latest_path,
        files=files,
        excerpts=excerpts,
    )


def collect_source_checkpoints(
    source: Path,
    allowed_languages: list[str],
    *,
    output_root: Path | None = None,
    project: str = "",
) -> SourceCheckpoints:
    has_files = has_meaningful_source_files(source)
    inferred_language = infer_dominant_language(source, allowed_languages) if has_files else ""
    baseline = resolve_latest_design_baseline(output_root, project) if output_root and project else None
    return SourceCheckpoints(
        has_meaningful_files=has_files,
        inferred_language=inferred_language,
        has_existing_design=baseline is not None,
        latest_design_version=baseline.version if baseline else "",
    )


def resolve_effective_mode(command: str, mode: str, has_existing_design: bool, focus: str) -> str:
    if command == "/redesign":
        return "refine"
    if mode == "fresh":
        return "fresh"
    if mode == "refine":
        return "refine" if has_existing_design else "fresh"
    if has_existing_design:
        return "refine"
    return "fresh"


def init_session_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                command TEXT NOT NULL,
                project TEXT NOT NULL,
                source_path TEXT NOT NULL,
                output_path TEXT NOT NULL,
                options_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                project TEXT NOT NULL,
                source_path TEXT NOT NULL,
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
            );
            """
        )


def record_run(db_path: Path, cfg: RunConfig, output_path: Path) -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    options_json = json.dumps(
        {
            "language": cfg.language,
            "style": cfg.style,
            "cloud": cfg.cloud,
            "web_search": cfg.web_search,
            "mode": cfg.mode,
            "effective_mode": cfg.effective_mode,
            "focus": cfg.focus,
            "role": cfg.role,
            "prompt": cfg.prompt,
            "non_interactive": cfg.non_interactive,
        }
    )
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO runs (created_at, command, project, source_path, output_path, options_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now, cfg.command, cfg.project, str(cfg.source), str(output_path), options_json),
        )
        return int(cur.lastrowid)


def record_event(db_path: Path, run_id: int, event_type: str, content: str) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO events (run_id, event_type, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, event_type, content, now),
        )


def create_chat_session(db_path: Path, project: str, source_path: Path, title: str) -> str:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    session_id = sha256(f"{project}:{source_path}:{now}".encode("utf-8")).hexdigest()[:12]
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (session_id, created_at, updated_at, project, source_path, title)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, now, now, project, str(source_path), title),
        )
    return session_id


def touch_chat_session(db_path: Path, session_id: str, title: str | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        if title:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ?, title = ? WHERE session_id = ?",
                (now, title, session_id),
            )
        else:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )


def add_chat_message(db_path: Path, session_id: str, role: str, content: str) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, now),
        )
    touch_chat_session(db_path, session_id)


def get_chat_session(db_path: Path, session_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        session_row = conn.execute(
            """
            SELECT session_id, created_at, updated_at, project, source_path, title
            FROM chat_sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if not session_row:
            return None
        messages = conn.execute(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()
    return {
        "session_id": session_row["session_id"],
        "created_at": session_row["created_at"],
        "updated_at": session_row["updated_at"],
        "project": session_row["project"],
        "source_path": session_row["source_path"],
        "title": session_row["title"],
        "messages": [
            {"role": row["role"], "content": row["content"], "created_at": row["created_at"]}
            for row in messages
        ],
    }


def list_chat_sessions(db_path: Path, limit: int = 20) -> list[dict[str, str]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT session_id, created_at, updated_at, project, source_path, title
            FROM chat_sessions
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def should_enable_web_search(mode: str, prompt: str, focus: str, cloud: str) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False

    text = f"{prompt}\n{focus}".lower()
    keywords = {
        "latest",
        "current",
        "compliance",
        "gdpr",
        "hipaa",
        "soc2",
        "pci",
        "pricing",
        "cost",
        "sla",
        "kubernetes",
        "cloud",
        "managed",
    }
    return any(keyword in text for keyword in keywords) or cloud in {"aws", "gcp", "azure", "hybrid"}


def best_effort_search(query: str, enabled: bool, limit: int = 5) -> list[dict[str, str]]:
    if not enabled or not query.strip():
        return []
    try:
        from ddgs import DDGS  # type: ignore

        with DDGS() as ddgs:
            results: list[dict[str, str]] = []
            for item in ddgs.text(query, max_results=limit):
                title = str(item.get("title", "")).strip()
                href = str(item.get("href", "")).strip()
                snippet = str(item.get("body", "")).strip()
                if href:
                    results.append({"title": title, "url": href, "snippet": snippet})
            return results
    except Exception:
        return []


def source_inventory(source: Path) -> dict[str, Any]:
    files: list[Path] = []
    ext_count: dict[str, int] = {}

    for root, dirs, names in os.walk(source):
        dirs[:] = [item for item in dirs if item not in SKIP_DIRS]
        for name in names:
            path = Path(root) / name
            if path.name.startswith("."):
                continue
            rel = path.relative_to(source)
            files.append(rel)
            ext = path.suffix.lower() or "<noext>"
            ext_count[ext] = ext_count.get(ext, 0) + 1

    files_sorted = sorted(files, key=lambda item: (len(item.parts), str(item)))
    top_files = [str(item) for item in files_sorted[:TOP_FILE_LIMIT]]
    modules = []
    for name in ["agents", "api", "services", "utils", "ui", "schemas", "graph", "rules"]:
        path = source / name
        if path.exists() and path.is_dir():
            modules.append({"name": name, "files": sum(1 for item in path.rglob("*") if item.is_file())})

    return {
        "total_files": len(files),
        "extensions": dict(sorted(ext_count.items(), key=lambda pair: (-pair[1], pair[0]))),
        "modules": modules,
        "top_files": top_files,
    }


def detect_stack(source: Path) -> dict[str, Any]:
    stack = {"language": [], "frameworks": [], "storage": [], "runtime": []}
    files_to_scan = [source / "pyproject.toml", source / "requirements.txt", source / "README.md"]
    blob = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore").lower()
        for path in files_to_scan
        if path.exists()
    )

    if (source / "pyproject.toml").exists() or (source / "requirements.txt").exists():
        stack["language"].append("Python")
    if (source / "ui" / "package.json").exists():
        stack["language"].append("JavaScript")

    for key, label in [
        ("fastapi", "FastAPI"),
        ("langgraph", "LangGraph"),
        ("langchain", "LangChain"),
        ("uvicorn", "Uvicorn"),
        ("sqlite", "SQLite"),
        ("ollama", "Ollama"),
        ("react", "React"),
        ("vite", "Vite"),
    ]:
        if key in blob:
            if label == "SQLite":
                stack["storage"].append(label)
            elif label == "Uvicorn":
                stack["runtime"].append(label)
            else:
                stack["frameworks"].append(label)

    if not stack["storage"]:
        stack["storage"].append("SQLite")

    for key in stack:
        stack[key] = sorted(set(stack[key]))
    return stack


def map_modules(source: Path) -> dict[str, str]:
    descriptions = {
        "agents": "Domain agents responsible for extraction, architecture drafting, diagram shaping, and revision passes.",
        "api": "Local FastAPI surface used by the simple OSS UI.",
        "services": "Runtime adapters for search, LLM configuration, storage, and session handling.",
        "utils": "Formatting, memory compaction, diagram stability, and document helpers.",
        "ui": "Local browser UI for prompt entry and inspecting generated outputs.",
        "schemas": "Pydantic request and response schemas for API contracts.",
        "graph": "Workflow orchestration layer coordinating agent execution.",
        "rules": "Prompt rules and edge-case handling logic.",
    }
    module_map: dict[str, str] = {}
    for name, description in descriptions.items():
        path = source / name
        if path.exists() and path.is_dir():
            module_map[name] = description
    return module_map


def identify_key_paths(source: Path) -> list[str]:
    candidates = [
        "main.py",
        "pyproject.toml",
        "README.md",
        "docs/cli.md",
        "api/routes.py",
        "ui/src/App.jsx",
        "desysflow_cli/__main__.py",
    ]
    return [item for item in candidates if (source / item).exists()]


def choose_version(project_root: Path) -> tuple[str, Path, Path | None]:
    project_root.mkdir(parents=True, exist_ok=True)
    versions = []
    for child in project_root.iterdir():
        if child.is_dir() and child.name.startswith("v"):
            try:
                versions.append(int(child.name[1:]))
            except ValueError:
                continue
    previous = max(versions) if versions else 0
    next_version = previous + 1
    prev_path = project_root / f"v{previous}" if previous else None
    return f"v{next_version}", project_root / f"v{next_version}", prev_path


def cli_db_path(output_root: Path) -> Path:
    return output_root / ".desysflow_cli.db"


def read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def style_notes(style: str) -> dict[str, str]:
    if style == "minimal":
        return {
            "detail": "Concise sections focused on the decisions required to build and ship the system.",
            "test_depth": "Critical-path test strategy only.",
        }
    if style == "detailed":
        return {
            "detail": "Comprehensive coverage with explicit trade-offs, failure paths, and implementation notes.",
            "test_depth": "Expanded test matrix across functional and non-functional paths.",
        }
    return {
        "detail": "Balanced detail with enough implementation guidance to be practical without becoming noisy.",
        "test_depth": "Core functional and resilience test plan.",
    }


def build_analysis_context(cfg: RunConfig) -> AnalysisContext:
    intent_text = cfg.prompt.strip() or cfg.focus.strip() or cfg.project
    web_enabled = should_enable_web_search(cfg.web_search, intent_text, cfg.focus, cfg.cloud)
    search_query = f"{cfg.project} {intent_text} {cfg.cloud}".strip()

    with ThreadPoolExecutor(max_workers=6) as executor:
        inventory_future = executor.submit(source_inventory, cfg.source)
        stack_future = executor.submit(detect_stack, cfg.source)
        module_future = executor.submit(map_modules, cfg.source)
        paths_future = executor.submit(identify_key_paths, cfg.source)
        refs_future = executor.submit(best_effort_search, search_query, web_enabled, 5)
        baseline_future = executor.submit(resolve_latest_design_baseline, cfg.output_root, cfg.project)

    return AnalysisContext(
        inventory=inventory_future.result(),
        stack=stack_future.result(),
        module_map=module_future.result(),
        key_paths=paths_future.result(),
        web_enabled=web_enabled,
        references=refs_future.result(),
        latest_design=baseline_future.result(),
    )


def build_mermaid(ctx: AnalysisContext, cfg: RunConfig) -> str:
    modules = set(ctx.module_map.keys())
    lines = [
        "flowchart TD",
        "    DeveloperUser[Developer] --> DesysflowCli[DesysFlow CLI]",
        "    DesysflowCli --> DesignOrchestrator[Local Design Orchestrator]",
        "    DesignOrchestrator --> RequirementsExtractor[Requirements Extractor]",
        "    DesignOrchestrator --> ArchitecturePlanner[Architecture Planner]",
        "    DesignOrchestrator --> MermaidRenderer[Mermaid Renderer]",
        "    DesignOrchestrator --> DocumentPackager[Document Packager]",
        "    DesignOrchestrator --> ReviewLoop[Reviewer Loop]",
        "    ReviewLoop --> VersionedOutput[Versioned DesysFlow Output]",
        "    DesysflowCli --> LocalSessionDb[(Local SQLite Session DB)]",
        "    LocalSessionDb --> VersionedOutput",
    ]

    if "api" in modules:
        lines.append("    DesignOrchestrator --> LocalApi[Local API Layer]")
    if "ui" in modules:
        lines.append("    DesysflowCli --> WorkspaceUi[Local Workspace UI]")
    if "services" in modules:
        lines.append("    DesignOrchestrator --> ServiceAdapters[Service Adapters]")
    if cfg.cloud != "local":
        lines.append(f"    DocumentPackager --> CloudProfile[{cfg.cloud.upper()} Deployment Profile]")
        lines.append("    CloudProfile --> VersionedOutput")
    return "\n".join(lines) + "\n"


def build_user_request(cfg: RunConfig, ctx: AnalysisContext) -> str:
    key_paths = ", ".join(ctx.key_paths[:8]) if ctx.key_paths else "repository root files"
    base = [
        f"Role: {cfg.role}",
        f"Project: {cfg.project}",
        f"Preferred implementation language: {cfg.language}",
        f"Cloud target: {cfg.cloud}",
        f"Design style: {cfg.style}",
        f"Reference paths: {key_paths}",
    ]
    if cfg.prompt.strip():
        base.append(f"Design request: {cfg.prompt.strip()}")
    elif cfg.focus.strip():
        base.append(f"Design request: {cfg.focus.strip()}")
    else:
        base.append(
            "Design request: Create a production-grade architecture for the current codebase, "
            "including API boundaries, data flow, scaling, availability, and security."
        )
    if ctx.latest_design:
        base.append(
            f"Existing .desysflow baseline: version {ctx.latest_design.version} at {ctx.latest_design.path}"
        )
        baseline_files = ", ".join(ctx.latest_design.files) if ctx.latest_design.files else "no readable baseline docs"
        base.append(f"Baseline files loaded: {baseline_files}")
        for name in ["SUMMARY.md", "HLD.md", "LLD.md", "TECHNICAL_REPORT.md"]:
            excerpt = ctx.latest_design.excerpts.get(name, "").strip()
            if excerpt:
                base.append(f"Baseline excerpt from {name}:\n{excerpt}")
    return "\n".join(base)


def _pretty(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2)
    return str(value)


def _bullet_list(items: list[Any], fallback: str = "- Not specified.") -> str:
    if not items:
        return fallback
    return "\n".join(f"- {_pretty(item)}" for item in items)


def _safe_text(value: Any, fallback: str = "Not specified.") -> str:
    if isinstance(value, str):
        compact = " ".join(value.split()).strip()
        return compact if compact else fallback
    if value is None:
        return fallback
    return str(value)


def _infer_component_type(name: str, responsibility: str) -> str:
    text = f"{name} {responsibility}".lower()
    if any(token in text for token in ["gateway", "ingress", "edge"]):
        return "gateway"
    if any(token in text for token in ["postgres", "mysql", "mongodb", "database", "store", "warehouse"]):
        return "database"
    if any(token in text for token in ["redis", "cache", "memcached"]):
        return "cache"
    if any(token in text for token in ["queue", "kafka", "pubsub", "sqs", "stream"]):
        return "queue"
    if any(token in text for token in ["s3", "gcs", "blob", "object storage", "storage"]):
        return "storage"
    if any(token in text for token in ["cdn", "edge cache"]):
        return "cdn"
    if any(token in text for token in ["monitor", "alert", "observability", "metrics", "logging", "tracing"]):
        return "monitoring"
    return "service"


def _format_component_bullets(components: list[Any], fallback: list[dict[str, str]] | None = None) -> str:
    normalized: list[dict[str, str]] = []
    for item in components:
        if isinstance(item, dict):
            name = _safe_text(item.get("name"), "Unnamed Component")
            responsibility = _safe_text(item.get("responsibility"), "Responsibility not specified.")
            comp_type = _safe_text(item.get("type"), _infer_component_type(name, responsibility)).lower()
        else:
            name = _safe_text(item, "Unnamed Component")
            responsibility = "Supports core platform capabilities."
            comp_type = _infer_component_type(name, responsibility)
        normalized.append({"name": name, "responsibility": responsibility, "type": comp_type})

    if not normalized and fallback:
        normalized = fallback
    if not normalized:
        normalized = [
            {
                "name": "Core Service",
                "responsibility": "Coordinate request processing and downstream calls",
                "type": "service",
            }
        ]

    blocks = []
    for obj in normalized:
        lines = json.dumps(obj, indent=2).splitlines()
        if not lines:
            continue
        blocks.append("- " + lines[0])
        blocks.extend(f"  {line}" for line in lines[1:])
    return "\n".join(blocks)


def _format_api_endpoint_line(item: Any) -> str:
    if not isinstance(item, dict):
        return _safe_text(item)
    method = _safe_text(item.get("method"), "METHOD").upper()
    path = _safe_text(item.get("path"), "/")
    description = _safe_text(item.get("description"), "No description.")
    request_body = _safe_text(item.get("request_body"), "{}")
    response_body = _safe_text(item.get("response_body"), "{}")
    return f"`{method} {path}` - {description} | request={request_body} | response={response_body}"


def render_hld(cfg: RunConfig, version: str, ctx: AnalysisContext) -> str:
    style_hint = style_notes(cfg.style)
    module_components = [
        {
            "name": _safe_text(name, "Core Module"),
            "responsibility": _safe_text(description, "Core system responsibility."),
            "type": _infer_component_type(_safe_text(name), _safe_text(description)),
        }
        for name, description in ctx.module_map.items()
    ]
    cloud_text = (
        f"- Target cloud profile: `{cfg.cloud}`\n- Prefer managed building blocks where portability does not materially suffer."
        if cfg.cloud != "local"
        else "- Target cloud profile: `local` (cloud-agnostic baseline)."
    )

    return f"""# HLD

## Overview
- Project: `{cfg.project}`
- Version: `{version}`
- Source path: `{cfg.source}`
- Preferred language: `{cfg.language}`
- Report style: `{cfg.style}`

This high-level design is generated from the current source tree. {style_hint["detail"]}

## Components
{_format_component_bullets(module_components)}

## Data Flow
1. The local CLI accepts `/design` inputs and routes fresh vs refine behavior smartly.
2. Parallel sub-agents inspect the repo, stack, and module boundaries.
3. Architecture, diagram, and report drafts are produced concurrently.
4. A lightweight reviewer loop improves structure, wording, and Mermaid consistency.
5. Final artifacts are written into the versioned `desysflow/` dump.

## Scaling and Availability
- Sub-agent steps are independent and can run concurrently for faster local generation.
- Outputs are deterministic text files, which keeps refine diffs readable in git.
- SQLite is sufficient for OSS local usage and avoids introducing unnecessary infrastructure.

## Cloud Guidance
{cloud_text}

## Trade-offs
- Static repo inspection is reliable and reproducible, but it cannot infer every unstated business constraint.
- Keeping the review loop lightweight improves output quality without turning the OSS workflow into a heavyweight gated review product.

## Future Improvements
- Add explicit capacity envelopes per critical service with SLO/SLA mappings.
- Introduce clearer cost tiering guidance for local, cloud, and hybrid deployments.
- Extend architecture variants with migration pathways for growth stages.
"""


def render_lld(cfg: RunConfig, ctx: AnalysisContext) -> str:
    style_hint = style_notes(cfg.style)
    key_paths = "\n".join(f"- `{item}`" for item in ctx.key_paths) or "- No representative paths detected."
    return f"""# LLD

## Implementation Scope
- Convert architecture decisions into implementation tasks, contracts, and deployment controls.
- Keep operational behavior explicit: retries, timeouts, observability, and rollback paths.

## APIs
- `desysflow /design --source . --out ./.desysflow`
- `desysflow /design --source . --out ./.desysflow --focus "<goal>"` to refine from latest
- `desysflow /redesign ...` remains as a compatibility alias for explicit refine runs

## Schemas
- `METADATA.json`: run metadata, hashes, and parent version references.
- `TREE.md`: emitted folder tree for the current design version.

## Service Communication
- Extraction, drafting, diagramming, and report generation run as parallel local sub-agents.
- The reviewer loop consumes draft artifacts and applies small deterministic fixes before packaging.

## Caching
- Session runs and event logs are stored in SQLite via `.desysflow_cli.db`.
- No Redis, vector store, or external cache is required for the OSS CLI flow.

## Error Handling
- `/design` routes to `fresh` or `refine` mode based on project state and user intent.
- `/redesign` falls back to fresh generation when no prior version exists.
- Web search runs on a best-effort basis and never blocks generation.
- Reviewer-loop failures degrade to the latest valid draft rather than aborting the run.
- Fail-safe behavior prioritizes valid artifact output over partial pipeline failure.

## Deployment
- Local execution target: Python 3.11+.
- CI target: run the CLI and commit the generated `desysflow/` dump when desired.
- Preferred implementation language for recommendations: `{cfg.language}`
- Representative repo paths considered during analysis:
{key_paths}

## Security
- The generator reads local source files and writes Markdown, Mermaid, and JSON artifacts only.
- Secrets are not intentionally extracted or copied into generated docs.
- Access scope remains local-first; no hosted control plane is required for core workflows.

## Test Plan
- {style_hint["test_depth"]}
- Confirm `diagram.mmd` starts with `flowchart TD`.
- Confirm required markdown sections are present after each run.

## Future Improvements
- Add API versioning and backward-compatibility checks into the refine workflow.
- Add richer schema evolution guidance with migration and rollback notes.
- Expand failure-mode playbooks with concrete SLO-linked remediation steps.
"""


def render_technical_report(cfg: RunConfig, ctx: AnalysisContext, version: str) -> str:
    refs_md = "\n".join(
        f"- [{item['title'] or item['url']}]({item['url']}) - {item['snippet'][:160]}"
        for item in ctx.references
    ) or "- No external references used for this run."
    extension_lines = "\n".join(
        f"- `{ext}`: {count}" for ext, count in list(ctx.inventory["extensions"].items())[:12]
    )
    return f"""# TECHNICAL REPORT

## Executive Summary
This versioned design package was generated from repository inspection using an OSS-first local workflow. The tool favors parallel analysis, deterministic outputs, and a minimal operational footprint.

## Detected Stack
- Languages: {", ".join(ctx.stack["language"]) or "Unknown"}
- Frameworks: {", ".join(ctx.stack["frameworks"]) or "Unknown"}
- Storage: {", ".join(ctx.stack["storage"]) or "Unknown"}
- Runtime: {", ".join(ctx.stack["runtime"]) or "Unknown"}
- Preferred implementation language: {cfg.language}

## Sub-agent Topology
- Extractor sub-agent: builds the repository inventory and key-path map.
- Architecture sub-agent: synthesizes the main structural narrative and trade-offs.
- Diagram sub-agent: emits the Mermaid architecture view.
- Report sub-agent: assembles HLD, LLD, summary, and metadata.
- Reviewer sub-agent: runs small iterative checks to improve completeness and clarity.

## Parallel Execution Plan
- Analysis stage runs inventory, stack detection, module mapping, and optional web grounding in parallel.
- Draft stage runs HLD, LLD, Mermaid, and technical-report generation in parallel.
- Packaging stage writes docs, metadata, folder tree, and diff output.

## Internal Reviewer Loop
- Runs up to `{REVIEW_LOOP_LIMIT}` passes per command.
- Acts as the lightweight critic-in-the-loop for architecture quality.
- Checks required headings, Mermaid prefix validity, OSS-scope wording, and cross-document consistency.
- Fixes small structural gaps automatically instead of exposing a separate user-facing review workflow.

## Context Bloat Fixes
- Representative file inventory is capped at `TOP_FILE_LIMIT={TOP_FILE_LIMIT}`.
- Session state is summarized into SQLite records instead of long in-memory chains.
- Refine runs write a fresh versioned package rather than appending fragmented outputs.

## Session Management and Memory
- Run history is stored in `.desysflow/.desysflow_cli.db`.
- No external product-memory layer is required.

## Web Search Strategy
- User mode: `{cfg.web_search}`
- Effective mode: `{"enabled" if ctx.web_enabled else "disabled"}`
- Auto mode only activates for changing or external constraints such as cloud capabilities, compliance, or pricing.

## External References
{refs_md}

## Repository Signals
- Total files scanned: {ctx.inventory["total_files"]}
- Top extensions:
{extension_lines}
- Current output version: `{version}`

## Future Improvements
- Add deeper dependency graphing to improve impact analysis during refine runs.
- Add optional benchmark-backed sizing recommendations for common deployment profiles.
- Add stricter doc quality gates for API consistency, resilience notes, and rollback readiness.
"""


def render_pipeline(cfg: RunConfig, ctx: AnalysisContext) -> str:
    module_count = len(ctx.module_map)
    return f"""# PIPELINE

## Command
- Requested command: `{cfg.command}`
- Effective mode: `{cfg.effective_mode}`
- Focus: `{cfg.focus or "n/a"}`

## Parallel Sub-agents
1. Extractor: source inventory, key paths, and repo map.
2. Stack profiler: language, framework, storage, and runtime detection.
3. Architect: HLD and implementation framing.
4. Diagrammer: Mermaid flow draft.
5. Reporter: technical report, summary, and changelog.

## Reviewer Loop
1. Validate section coverage.
2. Validate Mermaid structure.
3. Remove SaaS-only or gated-product wording from OSS docs.
4. Tighten wording and consistency across HLD, LLD, and technical report.

## Scope Snapshot
- Modules detected: `{module_count}`
- Key paths sampled: `{len(ctx.key_paths)}`
- Web grounding references: `{len(ctx.references)}`
"""


def render_inventory(ctx: AnalysisContext) -> str:
    module_lines = "\n".join(f"- `{item['name']}`: {item['files']} files" for item in ctx.inventory["modules"])
    extension_lines = "\n".join(
        f"- `{ext}`: {count}" for ext, count in list(ctx.inventory["extensions"].items())[:12]
    )
    file_lines = "\n".join(f"- `{item}`" for item in ctx.inventory["top_files"])
    return f"""# SOURCE INVENTORY

- Total files: {ctx.inventory["total_files"]}

## Modules
{module_lines or "- No module directories found."}

## Extensions
{extension_lines}

## Representative Files
{file_lines}
"""


def render_summary(cfg: RunConfig, version: str, ctx: AnalysisContext) -> str:
    return f"""# SUMMARY

- Command: `{cfg.command}`
- Effective mode: `{cfg.effective_mode}`
- Project: `{cfg.project}`
- Version: `{version}`
- Output: `{cfg.output_root / cfg.project / version}`
- Language: `{cfg.language}`
- Style: `{cfg.style}`
- Cloud: `{cfg.cloud}`
- Web search: `{cfg.web_search}` -> `{"enabled" if ctx.web_enabled else "disabled"}`
- Parallel sub-agents: `enabled`
- Internal reviewer loop: `enabled`

Generated files:
- `HLD.md`
- `LLD.md`
- `TECHNICAL_REPORT.md`
- `NON_TECHNICAL_DOC.md`
- `diagram.mmd`
- `TREE.md`
- `METADATA.json`
- `CHANGELOG.md`
- `DIFF.md`
"""


def render_changelog(cfg: RunConfig, version: str, ctx: AnalysisContext) -> str:
    return f"""# CHANGELOG

## {version}
- Command: `{cfg.command}`
- Effective mode: `{cfg.effective_mode}`
- Language: `{cfg.language}`
- Focus: `{cfg.focus or "n/a"}`
- Report style: `{cfg.style}`
- Cloud target: `{cfg.cloud}`
- Web search effective: `{"enabled" if ctx.web_enabled else "disabled"}`
- Parallel sub-agents: `enabled`
- Reviewer loop: `enabled`
"""


def render_non_technical_doc(cfg: RunConfig, ctx: AnalysisContext, version: str) -> str:
    module_count = len(ctx.module_map)
    core_users = ", ".join(["founders", "product leads", "engineering managers", "developers"])
    key_capabilities = [
        "Turns a source tree or prompt into a versioned design package",
        "Keeps sessions, chat history, and artifacts local under ./.desysflow",
        "Supports iterative refinement without losing earlier versions",
        "Produces outputs usable by both technical and non-technical stakeholders",
    ]
    capability_lines = "\n".join(f"- {item}" for item in key_capabilities)
    future_lines = "\n".join(
        [
            "- Add stronger roadmap and phase-planning views for stakeholder discussions.",
            "- Add effort, cost, and deployment comparison summaries for different operating models.",
            "- Improve side-by-side version comparison for design evolution over time.",
            "- Add reusable templates for product categories such as SaaS, internal tools, and data platforms.",
        ]
    )
    return f"""# NON-TECHNICAL DOC

## Product Summary
- Project: `{cfg.project}`
- Version: `{version}`
- Positioning: local-first design workspace for architecture planning and refinement
- Preferred language for implementation guidance: `{cfg.language}`

This package is intended to help teams move from idea to implementation plan with less ambiguity and less overhead than a heavyweight hosted workflow.

## Business Value
- Provides a shared planning artifact for product, engineering, and delivery conversations.
- Speeds up early-stage technical scoping by generating architecture, implementation, and review-ready outputs in one run.
- Keeps outputs versioned and local, which makes change tracking easier for teams working directly in code repositories.

## Target Users
- Core users: {core_users}
- Best fit: teams that want practical design outputs without a complex platform setup
- Current repo signals considered: `{module_count}` major module areas and `{ctx.inventory["total_files"]}` scanned files

## Key Capabilities
{capability_lines}

## Delivery Shape
- Output location: `desysflow/{cfg.project}/{version}`
- Primary generated assets: architecture diagram, technical document, implementation detail, and project brief
- Collaboration style: one local workspace with versioned design history
- Cloud target framing: `{cfg.cloud}`

## Risks and Constraints
- Generated outputs are only as strong as the constraints visible in the source tree and prompt.
- Business priorities such as pricing, compliance scope, and launch sequencing may still require human refinement.
- Local-first simplicity reduces operational overhead, but limits built-in multi-user workflow features.

## Future Improvements
{future_lines}
"""


def render_hld_from_workflow(cfg: RunConfig, version: str, result: dict[str, Any], user_request: str) -> str:
    hld = result.get("hld_report", {}) or {}
    components = hld.get("components", []) if isinstance(hld.get("components"), list) else []
    data_flow = hld.get("data_flow", []) if isinstance(hld.get("data_flow"), list) else []
    trade_offs = hld.get("trade_offs", []) if isinstance(hld.get("trade_offs"), list) else []
    capacity = hld.get("estimated_capacity", {}) if isinstance(hld.get("estimated_capacity"), dict) else {}
    fallback_components = [
        {"name": "API Gateway", "responsibility": "Route and rate-limit client requests", "type": "gateway"},
        {"name": "Auth Service", "responsibility": "Validate OAuth2 tokens and enforce IAM policies", "type": "service"},
        {"name": "Feature Store", "responsibility": "Persist and query training features", "type": "database"},
        {"name": "Training Orchestrator", "responsibility": "Trigger Vertex AI pipelines", "type": "service"},
        {"name": "Training Scheduler", "responsibility": "Schedule periodic training jobs", "type": "service"},
        {"name": "Model Serving Cluster", "responsibility": "Serve models with low latency", "type": "service"},
        {"name": "Batch Inference Engine", "responsibility": "Process bulk inference requests", "type": "service"},
        {"name": "Experiment Tracker", "responsibility": "Track experiments and metrics", "type": "service"},
        {"name": "CLI Service", "responsibility": "Expose CLI commands via Cloud Functions", "type": "service"},
        {"name": "Logging Service", "responsibility": "Collect logs to Cloud Logging", "type": "service"},
        {
            "name": "Monitoring & Alerting Service",
            "responsibility": "Aggregate metrics and trigger alerts",
            "type": "monitoring",
        },
        {"name": "Secrets Manager", "responsibility": "Store DB credentials and API keys", "type": "service"},
    ]
    assumptions = [
        "Current prompt and repository context represent the primary product scope.",
        "Non-functional targets are derived from extracted requirements when explicit values are missing.",
        "Cloud and runtime choices can be evolved in follow-up design iterations.",
    ]
    data_flow_lines = _bullet_list(data_flow, fallback="- Request and processing flow not specified.")
    if data_flow:
        data_flow_lines = _bullet_list([f"Step {idx + 1}: {_safe_text(step)}" for idx, step in enumerate(data_flow)])
    capacity_lines = _bullet_list(
        [f"{_safe_text(k)}: {_safe_text(v)}" for k, v in capacity.items()],
        fallback="- Not specified.",
    )
    return f"""# HLD

## Overview
- Project: `{cfg.project}`
- Version: `{version}`
- Role: `{cfg.role}`
- Preferred language: `{cfg.language}`
- Cloud target: `{cfg.cloud}`

{hld.get("system_overview", "No overview generated.")}

## Scope and Assumptions
### Scope
- Architecture-level design for service boundaries, data flow, scaling, and reliability.
- Delivery-ready HLD that can be refined into implementation tasks.
### Assumptions
{_bullet_list(assumptions)}

## Components
{_format_component_bullets(components, fallback=fallback_components)}

## Data Flow
{data_flow_lines}

## Scaling and Availability
- Scaling strategy: {_safe_text(hld.get("scaling_strategy"))}
- Availability and DR: {_safe_text(hld.get("availability"))}
- Failure isolation: Services are expected to fail independently with retries, timeout guards, and graceful degradation.
- Recovery target guidance: Use rolling deploys and automated rollback triggers to reduce blast radius.

## Non-Functional Requirements
- Performance and latency: derived from extracted requirements and service topology.
- Reliability objective: high availability with graceful degradation on downstream failures.
- Security baseline: least privilege, encrypted transport, and auditable operational controls.

## Trade-offs
{_bullet_list(trade_offs)}

## Capacity Estimates
{capacity_lines}

## Prompt Context
- Input request:
```text
{user_request}
```

## Future Improvements
- Add workload-specific sizing validation against expected growth intervals.
- Add explicit cost/performance option sets per deployment model.
- Add migration runbooks for major architecture transitions.
"""


def render_lld_from_workflow(cfg: RunConfig, result: dict[str, Any]) -> str:
    lld = result.get("lld_report", {}) or {}
    apis = lld.get("api_endpoints", []) if isinstance(lld.get("api_endpoints"), list) else []
    dbs = lld.get("database_schemas", []) if isinstance(lld.get("database_schemas"), list) else []
    comms = lld.get("service_communication", []) if isinstance(lld.get("service_communication"), list) else []
    caching = lld.get("caching_strategy", []) if isinstance(lld.get("caching_strategy"), list) else []
    errors = lld.get("error_handling", []) if isinstance(lld.get("error_handling"), list) else []
    deployment = lld.get("deployment", {}) if isinstance(lld.get("deployment"), dict) else {}
    security = lld.get("security", []) if isinstance(lld.get("security"), list) else []
    return f"""# LLD

## Implementation Scope
- Translate architecture into APIs, schemas, communication contracts, and operations controls.
- Provide implementation guidance while keeping interfaces and failure behavior explicit.
- Keep behavior deterministic across environments: local, staging, and production.

## APIs
{_bullet_list([_format_api_endpoint_line(item) for item in apis])}

## Schemas
{_bullet_list([f"{_safe_text(item.get('name'), 'schema')} ({_safe_text(item.get('type'), 'unknown')}): tables={_safe_text(item.get('tables_or_collections'), '[]')}" for item in dbs])}

## Service Communication
{_bullet_list([f"{_safe_text(item.get('from'))} -> {_safe_text(item.get('to'))} via {_safe_text(item.get('protocol'))}: {_safe_text(item.get('description'))}" for item in comms])}

## Caching
{_bullet_list([f"Layer={_safe_text(item.get('layer'))}, tech={_safe_text(item.get('technology'))}, ttl={_safe_text(item.get('ttl'))}, invalidation={_safe_text(item.get('invalidation_strategy'))}" for item in caching])}

## Error Handling
{_bullet_list([f"Scenario={_safe_text(item.get('scenario'))}: strategy={_safe_text(item.get('strategy'))}; fallback={_safe_text(item.get('fallback'))}" for item in errors])}

## Deployment
{_bullet_list([f"{_safe_text(k)}: {_safe_text(v)}" for k, v in deployment.items()], fallback="- Not specified.")}

## Security
{_bullet_list(security)}

## Testing and Validation
- Contract tests for request/response schemas and compatibility.
- Integration tests for service communication and datastore boundaries.
- Resilience tests for timeout, retry, and fallback behavior.
- Load tests for critical APIs with p95/p99 tracking and alert thresholds.
- Security tests covering authn/authz controls and secret handling pathways.

## Future Improvements
- Add endpoint-by-endpoint SLA and idempotency contracts.
- Add schema migration/rollback playbooks for critical data models.
- Add detailed degradation modes for downstream dependency failures.
"""


def render_technical_report_from_workflow(
    cfg: RunConfig,
    ctx: AnalysisContext,
    version: str,
    result: dict[str, Any],
    user_request: str,
) -> str:
    refs_md = "\n".join(
        f"- [{item['title'] or item['url']}]({item['url']}) - {item['snippet'][:160]}"
        for item in ctx.references
    ) or "- No external references used for this run."
    components = result.get("hld_report", {}).get("components", [])
    api_endpoints = result.get("lld_report", {}).get("api_endpoints", [])
    requirements = result.get("requirements", {}) or {}
    return f"""# TECHNICAL REPORT

## Executive Summary
Prompt-driven workflow executed for role `{cfg.role}` and produced architecture artifacts for version `{version}`.

## Document Control
- Project: `{cfg.project}`
- Version: `{version}`
- Role: `{cfg.role}`
- Style: `{cfg.style}`
- Cloud target: `{cfg.cloud}`

## Sub-agent Topology
- Extractor -> template selector -> architecture generator -> edge-case injector -> primary selector.
- Diagram pipeline -> quality refinement.
- Report generator -> cloud infrastructure mapping.

## Parallel Execution Plan
- Repository context build runs in parallel (inventory, stack, modules, references).
- Document packaging runs in parallel where possible for markdown outputs.

## Internal Reviewer Loop
- Required-section validation and wording normalization pass.
- Mermaid prefix/shape validation pass.

## Context Bloat Fixes
- Representative files capped to `TOP_FILE_LIMIT={TOP_FILE_LIMIT}`.
- Outputs versioned per run to keep diffs small and traceable.

## Session Management and Memory
- Session and run metadata stored in local SQLite.
- Generated docs stored in versioned filesystem folders.

## Requirements Baseline
{_bullet_list([f"{k}: {v}" for k, v in requirements.items()], fallback="- Not available.")}

## Architecture Signals
- HLD components generated: {len(components) if isinstance(components, list) else 0}
- LLD API endpoints generated: {len(api_endpoints) if isinstance(api_endpoints, list) else 0}
- Cloud target: `{cfg.cloud}`
- Language target: `{cfg.language}`

## Quality and Risks
- Primary quality focus: maintainability, reliability, and observability.
- Delivery risk: requirement ambiguity when prompt details are sparse.
- Operational risk: dependency bottlenecks without capacity validation in runtime environment.

## Prompt Context
```text
{user_request}
```

## External References
{refs_md}

## Future Improvements
- Add automated architecture quality scoring across reliability, cost, and security dimensions.
- Add benchmark-derived capacity guidance for common traffic tiers.
- Add deeper refine-mode context stitching with prior version deltas.
"""


def render_non_technical_doc_from_workflow(result: dict[str, Any]) -> str:
    doc = build_non_technical_doc(result)
    return f"""# NON-TECHNICAL DOC

## Product Summary
- {doc.get("summary", "No summary generated.")}

## Business Value
{_bullet_list(doc.get("business_value", []) if isinstance(doc.get("business_value"), list) else [])}

## Target Users
{_bullet_list(doc.get("target_users", []) if isinstance(doc.get("target_users"), list) else [])}

## Delivery Shape
{_bullet_list([f"{k}: {v}" for k, v in (doc.get("delivery_shape", {}) or {}).items()], fallback="- Not specified.")}

## Future Improvements
{_bullet_list(doc.get("future_improvements", []) if isinstance(doc.get("future_improvements"), list) else [])}
"""


def render_docs(
    cfg: RunConfig,
    version: str,
    ctx: AnalysisContext,
    workflow_result: dict[str, Any] | None = None,
    user_request: str = "",
) -> dict[str, str]:
    if workflow_result:
        docs = {
            "HLD.md": render_hld_from_workflow(cfg, version, workflow_result, user_request),
            "LLD.md": render_lld_from_workflow(cfg, workflow_result),
            "TECHNICAL_REPORT.md": render_technical_report_from_workflow(cfg, ctx, version, workflow_result, user_request),
            "NON_TECHNICAL_DOC.md": render_non_technical_doc_from_workflow(workflow_result),
            "SUMMARY.md": render_summary(cfg, version, ctx),
            "CHANGELOG.md": render_changelog(cfg, version, ctx),
            "diagram.mmd": str(workflow_result.get("mermaid_code", "") or build_mermaid(ctx, cfg)),
        }
        docs, all_redacted = scrub_secrets_from_docs(docs)
        if all_redacted:
            print(f"[SECURITY] Scrubbed {len(all_redacted)} secret(s) from generated docs:")
            for r in all_redacted[:10]:
                print(f"  - {r}")
            if len(all_redacted) > 10:
                print(f"  ... and {len(all_redacted) - 10} more")
        return run_reviewer_loop(docs)

    with ThreadPoolExecutor(max_workers=6) as executor:
        hld_future = executor.submit(render_hld, cfg, version, ctx)
        lld_future = executor.submit(render_lld, cfg, ctx)
        report_future = executor.submit(render_technical_report, cfg, ctx, version)
        non_tech_future = executor.submit(render_non_technical_doc, cfg, ctx, version)
        diagram_future = executor.submit(build_mermaid, ctx, cfg)

    docs = {
        "HLD.md": hld_future.result(),
        "LLD.md": lld_future.result(),
        "TECHNICAL_REPORT.md": report_future.result(),
        "NON_TECHNICAL_DOC.md": non_tech_future.result(),
        "SUMMARY.md": render_summary(cfg, version, ctx),
        "CHANGELOG.md": render_changelog(cfg, version, ctx),
        "diagram.mmd": diagram_future.result(),
    }
    docs, all_redacted = scrub_secrets_from_docs(docs)
    if all_redacted:
        print(f"[SECURITY] Scrubbed {len(all_redacted)} secret(s) from generated docs:")
        for r in all_redacted[:10]:
            print(f"  - {r}")
        if len(all_redacted) > 10:
            print(f"  ... and {len(all_redacted) - 10} more")
    return run_reviewer_loop(docs)


def scrub_secrets_from_docs(docs: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Scrub secret patterns from all doc contents. Returns (scrubbed_docs, all_redacted)."""
    all_redacted: list[str] = []
    cleaned: dict[str, str] = {}
    for name, content in docs.items():
        scrubbed, redacted = scrub_secrets(content)
        cleaned[name] = scrubbed
        all_redacted.extend(redacted)
    return cleaned, all_redacted


def ensure_sections(content: str, sections: list[str], fallback_line: str) -> str:
    updated = content
    for section in sections:
        if section not in updated:
            updated = updated.rstrip() + f"\n\n{section}\n{fallback_line}\n"
    return updated


def normalize_oss_wording(content: str) -> str:
    replacements = {
        "premium critic": "internal reviewer loop",
        "Critic Premium": "Internal Reviewer Loop",
        "critic-only": "review-loop",
        "full critic": "lightweight reviewer",
    }
    updated = content
    for old, new in replacements.items():
        updated = updated.replace(old, new)
    return updated


def review_artifacts(docs: dict[str, str]) -> list[str]:
    findings: list[str] = []
    if not docs["diagram.mmd"].lstrip().startswith("flowchart TD"):
        findings.append("Mermaid diagram must start with `flowchart TD`.")
    for section in HLD_REQUIRED_SECTIONS:
        if section not in docs["HLD.md"]:
            findings.append(f"HLD missing required section: {section}")
    for section in LLD_REQUIRED_SECTIONS:
        if section not in docs["LLD.md"]:
            findings.append(f"LLD missing required section: {section}")
    for section in TECH_REPORT_REQUIRED_SECTIONS:
        if section not in docs["TECHNICAL_REPORT.md"]:
            findings.append(f"TECHNICAL_REPORT missing required section: {section}")
    if "premium" in docs["TECHNICAL_REPORT.md"].lower():
        findings.append("TECHNICAL_REPORT contains SaaS/premium wording.")
    for section in NON_TECH_REQUIRED_SECTIONS:
        if section not in docs["NON_TECHNICAL_DOC.md"]:
            findings.append(f"NON_TECHNICAL_DOC missing required section: {section}")
    return findings


def apply_review_fixes(docs: dict[str, str], findings: list[str]) -> dict[str, str]:
    updated = dict(docs)
    updated["HLD.md"] = ensure_sections(
        normalize_oss_wording(updated["HLD.md"]),
        HLD_REQUIRED_SECTIONS,
        "- Added by the internal reviewer loop to preserve required OSS structure.",
    )
    updated["LLD.md"] = ensure_sections(
        normalize_oss_wording(updated["LLD.md"]),
        LLD_REQUIRED_SECTIONS,
        "- Added by the internal reviewer loop to preserve required OSS structure.",
    )
    updated["TECHNICAL_REPORT.md"] = ensure_sections(
        normalize_oss_wording(updated["TECHNICAL_REPORT.md"]),
        TECH_REPORT_REQUIRED_SECTIONS,
        "- Added by the internal reviewer loop to preserve required OSS structure.",
    )
    updated["NON_TECHNICAL_DOC.md"] = ensure_sections(
        normalize_oss_wording(updated["NON_TECHNICAL_DOC.md"]),
        NON_TECH_REQUIRED_SECTIONS,
        "- Added by the internal reviewer loop to preserve required OSS structure.",
    )
    if "PIPELINE.md" in updated:
        updated["PIPELINE.md"] = normalize_oss_wording(updated["PIPELINE.md"])
    if "SUMMARY.md" in updated:
        updated["SUMMARY.md"] = normalize_oss_wording(updated["SUMMARY.md"])
    if "CHANGELOG.md" in updated:
        updated["CHANGELOG.md"] = normalize_oss_wording(updated["CHANGELOG.md"])

    if not updated["diagram.mmd"].lstrip().startswith("flowchart TD"):
        updated["diagram.mmd"] = "flowchart TD\n    A[Reviewer Loop] --> B[Fixed Mermaid header]\n"

    if findings:
        review_note = "\n\n## Reviewer Notes\n" + "\n".join(f"- {item}" for item in findings) + "\n"
        if "## Reviewer Notes" not in updated["TECHNICAL_REPORT.md"]:
            updated["TECHNICAL_REPORT.md"] = updated["TECHNICAL_REPORT.md"].rstrip() + review_note
    return updated


def run_reviewer_loop(docs: dict[str, str]) -> dict[str, str]:
    current = dict(docs)
    for _ in range(REVIEW_LOOP_LIMIT):
        findings = review_artifacts(current)
        if not findings:
            break
        current = apply_review_fixes(current, findings)
    return current


def folder_tree(root: Path) -> str:
    lines = ["# TREE", "", f"Root: `{root}`", "", "```text"]
    for base, dirs, files in os.walk(root):
        rel = Path(base).relative_to(root)
        depth = len(rel.parts)
        indent = "  " * depth
        label = "." if str(rel) == "." else rel.name
        lines.append(f"{indent}{label}/")
        for file_name in sorted(files):
            lines.append(f"{indent}  {file_name}")
        dirs[:] = sorted(dirs)
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_artifacts(target: Path, docs: dict[str, str], metadata: dict[str, Any]) -> None:
    # Scrub api_key fields from metadata before writing
    safe_meta = {k: ("[REDACTED]" if "api_key" in k.lower() and v else v) for k, v in metadata.items()}
    target.mkdir(parents=True, exist_ok=True)
    for name, content in docs.items():
        (target / name).write_text(content.strip() + "\n", encoding="utf-8")
    (target / "METADATA.json").write_text(json.dumps(safe_meta, indent=2) + "\n", encoding="utf-8")


def _short_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:12]


def _fmt_size_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def _print_run_header(cfg: RunConfig, target: Path, version: str, previous: Path | None) -> None:
    print("")
    action = "Refining the design" if cfg.effective_mode == "refine" else "Starting a new design run"
    log_line("run", action)
    print(f"   Project: {cfg.project} • Version: {version}")
    if previous is not None:
        print(f"   Base: {previous.name}")
    print(f"   Setup: {cfg.language} • {cfg.style} • {cfg.cloud} • {cfg.role}")
    print(f"   Model: {(cfg.model_provider or 'auto')} / {(cfg.model_name or 'auto')}")
    print(f"   Request: {_truncate_cli_text(cfg.prompt or cfg.focus or 'Infer from the current codebase')}")
    print(f"   Output: {target}")


def _print_doc_status(docs: dict[str, str]) -> None:
    log_line("status", "Built the final artifact set.")
    for name, content in docs.items():
        size = len(content.encode("utf-8"))
        print(f"   📄 {name:<20} {_fmt_size_bytes(size):>8}  sha={_short_hash(content)}")


def _print_written_status(path: Path) -> None:
    log_line("status", "Saved generated files.")
    file_names = sorted(item.name for item in path.iterdir() if item.is_file())
    for name in file_names:
        file_path = path / name
        print(f"   📄 {name:<20} {_fmt_size_bytes(file_path.stat().st_size):>8}")


def _cli_progress_config(effective_mode: str) -> tuple[list[dict[str, str]], dict[str, str], str]:
    if effective_mode == "refine":
        return FOLLOWUP_PROGRESS_STEPS, FOLLOWUP_NODE_TO_STAGE, "context"
    return DESIGN_PROGRESS_STEPS, DESIGN_NODE_TO_STAGE, "scope"


def build_diff(previous: Path | None, current_docs: dict[str, str]) -> str:
    if not previous or not previous.exists():
        return "# DIFF\n\nNo previous version found; this run initialized the baseline design package.\n"

    lines = ["# DIFF", ""]
    for name, current in current_docs.items():
        old = read_text_or_empty(previous / name)
        if old == current:
            continue
        diff = difflib.unified_diff(
            old.splitlines(),
            current.splitlines(),
            fromfile=f"{previous.name}/{name}",
            tofile=f"current/{name}",
            lineterm="",
        )
        diff_text, _ = scrub_secrets("\n".join(diff))
        lines.append(f"## {name}")
        lines.append("```diff")
        lines.extend(diff_text.splitlines()[:250])
        lines.append("```")
        lines.append("")

    if len(lines) == 2:
        lines.append("No textual changes detected in generated artifacts.")
        lines.append("")
    return "\n".join(lines)


def run(cfg: RunConfig) -> int:
    require_llm_for_terminal()
    if not cfg.source.exists() or not cfg.source.is_dir():
        raise SystemExit(f"Source path is invalid: {cfg.source}")

    # Pre-scan source for potential secret leaks and warn the user
    secret_warnings = check_source_for_secrets(cfg.source)
    if secret_warnings:
        log_line("warn", "Possible secrets detected in source:")
        for w in secret_warnings[:5]:
            print(w)
        if len(secret_warnings) > 5:
            print(f"  ... and {len(secret_warnings) - 5} more files")
        log_line("hint", "Review generated docs before sharing.")
        if os.isatty(0):
            confirm = input("Continue? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                raise SystemExit("Aborted.")

    project_root = cfg.output_root / cfg.project
    version, target, previous = choose_version(project_root)
    _print_run_header(cfg, target, version, previous)
    if cfg.effective_mode == "refine" and previous is None:
        log_line("warn", "No baseline found for refine mode; running as fresh /design generation.")
        cfg = RunConfig(
            command=cfg.command,
            source=cfg.source,
            output_root=cfg.output_root,
            project=cfg.project,
            language=cfg.language,
            style=cfg.style,
            cloud=cfg.cloud,
            web_search=cfg.web_search,
            mode=cfg.mode,
            effective_mode="fresh",
            focus=cfg.focus,
            role=cfg.role,
            prompt=cfg.prompt,
            non_interactive=cfg.non_interactive,
            model_provider=cfg.model_provider,
            model_name=cfg.model_name,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )

    steps, node_to_stage, initial_stage = _cli_progress_config(cfg.effective_mode)
    step_labels = {item["key"]: item["label"] for item in steps}
    current_stage = initial_stage

    _stage_line(initial_stage, step_labels[initial_stage])
    ctx = build_analysis_context(cfg)
    log_line(
        "status",
        f"Scanned {len(ctx.module_map)} modules, {len(ctx.key_paths)} key paths, and {len(ctx.references)} references."
    )
    if ctx.web_enabled and not ctx.references:
        log_line("warn", "Web search was enabled, but no references were returned.")
    log_line("status", "Generating the design package. Local Ollama runs can take a few minutes.")
    user_request = build_user_request(cfg, ctx)

    def _on_workflow_update(node_key: str, _payload: dict[str, Any], _state: dict[str, Any]) -> None:
        nonlocal current_stage
        stage_key = node_to_stage.get(node_key)
        if stage_key and stage_key != current_stage:
            current_stage = stage_key
            _stage_line(stage_key, step_labels[stage_key])

    try:
        workflow_result = run_workflow_with_updates(
            user_request,
            diagram_style=cfg.style,
            preferred_language=cfg.language,
            on_update=_on_workflow_update,
        )
        hld_components = workflow_result.get("hld_report", {}).get("components", [])
        lld_apis = workflow_result.get("lld_report", {}).get("api_endpoints", [])
        log_line(
            "status",
            f"Drafted {len(hld_components) if isinstance(hld_components, list) else 0} components and "
            f"{len(lld_apis) if isinstance(lld_apis, list) else 0} API endpoints."
        )
    except Exception as exc:
        if is_llm_limit_error(exc):
            llm_cfg = get_llm_config()
            log_line("warn", "The model request hit provider limits.")
            print(f"   Provider: {llm_cfg.provider}")
            print(f"   Model: {llm_cfg.model}")
            print("   Try:")
            print("   - Shorten the prompt or focus.")
            print("   - Use --style minimal.")
            print("   - Use --web-search off.")
            raise SystemExit(1) from exc
        raise SystemExit(f"prompt-driven workflow failed: {exc}") from exc

    log_line("done", "Design workflow complete.")

    _stage_line("package", "Build the deliverables")
    log_line("status", "Assembling reports, diagram, and metadata.")
    docs = render_docs(cfg, version, ctx, workflow_result=workflow_result, user_request=user_request)
    _print_doc_status(docs)
    metadata = {
        "project": cfg.project,
        "version": version,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "command": cfg.command,
        "effective_mode": cfg.effective_mode,
        "language": cfg.language,
        "style": cfg.style,
        "cloud": cfg.cloud,
        "role": cfg.role,
        "prompt": cfg.prompt,
        "web_search_mode": cfg.web_search,
        "web_search_effective": ctx.web_enabled,
        "source_path": str(cfg.source),
        "source_sha256": sha256("\n".join(ctx.inventory["top_files"]).encode("utf-8")).hexdigest(),
        "mermaid_sha256": sha256(docs["diagram.mmd"].encode("utf-8")).hexdigest(),
        "parent_version": previous.name if previous else None,
        "subagents": ["extractor", "stack-profiler", "architect", "diagrammer", "reporter", "reviewer"],
        "review_loop_limit": REVIEW_LOOP_LIMIT,
        "generation_source": "llm_workflow",
        "llm_workflow_used": True,
    }

    _stage_line("write artifacts", "Write files")
    write_artifacts(target, docs, metadata)
    (target / "TREE.md").write_text(folder_tree(target), encoding="utf-8")
    (target / "DIFF.md").write_text(build_diff(previous, docs), encoding="utf-8")
    (project_root / "latest").write_text(version + "\n", encoding="utf-8")
    _print_written_status(target)

    _stage_line("update local session db", "Save session history")
    db_path = cli_db_path(cfg.output_root)
    init_session_db(db_path)
    run_id = record_run(db_path, cfg, target)
    record_event(db_path, run_id, "summary", f"Generated {version} for {cfg.project} in {cfg.effective_mode} mode")
    record_event(db_path, run_id, "subagents", "parallel extractor|stack-profiler|architect|diagrammer|reporter")
    record_event(db_path, run_id, "reviewer_loop", f"limit={REVIEW_LOOP_LIMIT}")
    record_event(db_path, run_id, "role", cfg.role)
    record_event(db_path, run_id, "language", cfg.language)
    record_event(db_path, run_id, "mode", f"requested={cfg.command}, effective={cfg.effective_mode}")
    if cfg.focus:
        record_event(db_path, run_id, "focus", cfg.focus)
    record_event(db_path, run_id, "web_search", f"enabled={ctx.web_enabled}, refs={len(ctx.references)}")

    log_line("done", f"Artifacts saved to {target}")
    log_line("done", f"Session history saved to {db_path}")
    log_line("hint", "Start with HLD.md, LLD.md, TECHNICAL_REPORT.md, NON_TECHNICAL_DOC.md, diagram.mmd, and DIFF.md.")
    return 0


def require_llm_for_terminal() -> None:
    status = check_llm_status()
    if status.get("status") == "available":
        return
    model = status.get("model", get_llm_config().model)
    provider = status.get("provider", get_llm_config().provider)
    message = status.get("message", "Model is not available.")
    print(f"LLM unavailable for provider={provider} model={model}")
    print(message)
    if not Path(".env.example").exists():
        print("Run ./scripts/bootstrap.sh for first-time model setup.")
    if provider == "ollama" and status.get("status") == "missing_model":
        print(f"Install it first with: ollama pull {model}")
    raise SystemExit(1)


def print_chat_session(session: dict[str, Any]) -> None:
    def _preview(value: str, limit: int = 160) -> str:
        one_line = " ".join(str(value).split())
        if len(one_line) <= limit:
            return one_line
        return one_line[: limit - 1] + "…"

    print(f"Session: {session['session_id']} | {session['title']}")
    if not session.get("messages"):
        print("No messages yet.")
        return
    for item in session["messages"][-12:]:
        role = str(item.get("role", "assistant")).upper()
        print(f"{role}: {_preview(item.get('content', ''))}")


def run_history(cfg: HistoryConfig) -> int:
    db_path = cli_db_path(cfg.output_root)
    init_session_db(db_path)
    sessions = list_chat_sessions(db_path, cfg.limit)
    if not sessions:
        print(f"No CLI chat sessions found in {cfg.output_root}.")
        return 0
    for item in sessions:
        print(f"{item['session_id']} | {item['updated_at']} | {item['project']} | {item['title']}")
    return 0


def make_run_config_from_chat(chat_cfg: ChatConfig, focus: str, role: str) -> RunConfig:
    return finalize_options(
        RunConfig(
            command="/design",
            source=chat_cfg.source,
            output_root=chat_cfg.output_root,
            project=chat_cfg.project,
            language="python",
            style="balanced",
            cloud="local",
            web_search="auto",
            mode="smart",
            effective_mode="",
            focus=focus,
            role=role,
            prompt=focus,
            non_interactive=True,
        )
    )


def run_chat(chat_cfg: ChatConfig) -> int:
    """Compatibility path for the old chat command.

    Keep the command as a single design run so
    existing scripts do not drop users into an interactive loop.
    """
    print("The chat command is now a compatibility alias. Running a single design generation.")
    return run(
        collect_run_args(
            "design",
            [
                "--source",
                str(chat_cfg.source),
                "--out",
                str(chat_cfg.output_root),
                "--project",
                chat_cfg.project,
            ],
        )
    )


def run_wizard() -> int:
    """Full interactive wizard — no arguments needed."""
    print("DesysFlow CLI")
    print("Basic setup.\n")

    # ── Model provider ─────────────────────────────────────────────
    providers = cfg_providers()
    print_sep("Model")
    provider_labels = [f"{p['label']} ({p.get('desc', p['id'])})" for p in providers]
    selected_provider_label = _ask_choice("Provider", provider_labels, provider_labels[0])
    provider_lookup = {provider_labels[idx]: providers[idx]["id"] for idx in range(len(providers))}
    provider = provider_lookup[selected_provider_label]

    # ── API key (GPT / Claude) ───────────────────────────────────
    api_key = ""
    if provider != "ollama":
        env_key = "OPENAI_API_KEY" if provider == "openai" else "ANTHROPIC_API_KEY"
        api_key = os.getenv(env_key, "").strip()
        if not api_key:
            print(f"\n  {provider.title()} selected — paste your API key below.")
            print("  (key is stored in env and not written to disk)\n")
            api_key = input(f"  API key: ").strip()
            if api_key:
                os.environ[env_key] = api_key

    # ── Base URL ─────────────────────────────────────────────────
    base_url_env_key = "OPENAI_BASE_URL" if provider == "openai" else ("ANTHROPIC_BASE_URL" if provider == "anthropic" else "OLLAMA_BASE_URL")
    base_url_default = (
        "https://api.openai.com/v1" if provider == "openai"
        else "https://api.anthropic.com" if provider == "anthropic"
        else "http://localhost:11434"
    )
    base_url = os.getenv(base_url_env_key, "").strip() or base_url_default
    os.environ[base_url_env_key] = base_url

    # ── Model name ───────────────────────────────────────────────
    prov_defaults = _provider_defaults()
    installed: list[str] = []
    if provider == "ollama":
        installed = list_ollama_models(base_url)

    default = prov_defaults.get(provider, {}).get("model", "") or (installed[0] if installed else "")
    print("")
    if provider == "ollama":
        model = _resolve_ollama_model_selection(installed, base_url, default)
    else:
        model = input(f"  Model name" + (f" [{default}]" if default else "") + ": ").strip() or default

    os.environ["MODEL_PROVIDER"] = provider
    if provider == "openai":
        os.environ["OPENAI_MODEL"] = model
    elif provider == "anthropic":
        os.environ["ANTHROPIC_MODEL"] = model
    else:
        os.environ["OLLAMA_MODEL"] = model

    # ── Source checkpoints ───────────────────────────────────────
    source_path = Path.cwd()
    project = default_project_name(source_path)
    output_root = default_output_root()
    languages = cfg_list("languages", ["python", "typescript", "go", "java", "rust"])
    source_checkpoints = collect_source_checkpoints(
        source_path,
        languages,
        output_root=output_root,
        project=project,
    )
    source_has_files = source_checkpoints.has_meaningful_files

    # ── Design preferences ───────────────────────────────────────
    print_sep("Design preferences")

    # ── Style ────────────────────────────────────────────────────
    styles = cfg_list("styles", ["minimal", "balanced", "detailed"])
    style_default = "balanced" if "balanced" in styles else styles[0]
    style = _ask_choice("Report style", [item.title() for item in styles], style_default.title()).lower()

    # ── Role ─────────────────────────────────────────────────────
    roles = cfg_list("roles", ["DevOps", "Principal Architect", "MLOps / AIOps"])
    role = _ask_choice("Role", roles, roles[0])

    # ── Mode ─────────────────────────────────────────────────────
    modes = cfg_list("design_modes", ["smart", "fresh", "refine"])
    mode = _ask_choice("Design mode", [item.title() for item in modes], modes[0].title()).lower()

    # ── Prompt / focus ───────────────────────────────────────────
    print_sep("Your design request")
    has_existing_design = source_checkpoints.has_existing_design
    language = languages[0]
    if source_has_files and source_checkpoints.inferred_language:
        language = source_checkpoints.inferred_language
        print(f"  Checkpoint: dominant repository language detected -> {language.title()}")
    if has_existing_design:
        print(
            "  Checkpoint: existing .desysflow baseline detected"
            f" -> {source_checkpoints.latest_design_version}"
        )
    language = _ask_choice("Language", [item.title() for item in languages], language.title()).lower()

    prompt_text, prompt_mode = _collect_prompt_text(
        source_has_files=source_has_files,
        has_existing_design=has_existing_design,
        latest_design_version=source_checkpoints.latest_design_version,
    )

    # ── Summary ───────────────────────────────────────────────────
    print_sep("Ready")
    print(f"  Provider   :  {provider.title()}")
    print(f"  Model      :  {model}")
    print(f"  Language   :  {language.title()}")
    print(f"  Style      :  {style.title()}")
    print(f"  Role       :  {role}")
    print(f"  Mode       :  {mode.title()}")
    print(f"  API key    :  {'[set]' if api_key else '[none / Ollama]'}")
    print(f"  Prompt     :  {prompt_text or '[auto-from-codebase]'}")
    print("")
    confirm = input("  Generate now? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        raise SystemExit("Cancelled.")

    # ── Build RunConfig & run ────────────────────────────────────
    defaults = cfg_defaults()
    effective_mode = resolve_effective_mode("/design", mode, has_existing_design, prompt_text)
    cfg = RunConfig(
        command="/design",
        source=source_path,
        output_root=output_root,
        project=project,
        language=language,
        style=style,
        cloud=defaults.get("cloud", "local"),
        web_search=defaults.get("search_mode", "auto"),
        mode=mode,
        effective_mode=effective_mode,
        focus=prompt_text,
        role=role,
        prompt=prompt_text,
        non_interactive=False,
        model_provider=provider,
        model_name=model,
        api_key=api_key,
        base_url=base_url,
    )
    cfg.non_interactive = True   # we already collected everything
    return run(cfg)


def collect_run_args(command: str, argv: list[str]) -> RunConfig:
    """Parse CLI flags; fall back to interactive prompt for anything missing."""
    cfg = parse_run_args(command, argv)

    # If provider / model are not set, collect them interactively
    interactive = not cfg.non_interactive and os.isatty(0)
    if interactive and not cfg.model_provider:
        cfg = resolve_model(cfg)

    return cfg


def clear() -> None:
    return None


def banner() -> str:
    return "DesysFlow CLI"


def print_sep(title: str) -> None:
    print("")
    print(f"  == {title} ==")
    print("")


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else list(os.sys.argv[1:])

    if not raw_args:
        if os.isatty(0):
            return run_wizard()
        print_main_help()
        return 0

    if raw_args[0] in {"help", "-h", "--help", "/help"}:
        print_main_help()
        return 0

    first = raw_args[0]

    # /letsvibedesign → interactive wizard (no args = wizard too)
    if first in {"/letsvibedesign", "wizard", "interactive"}:
        return run_wizard()

    # design / redesign → collect args (CLI flags → wizard if needed)
    if first in {"/design", "/redesign", "design", "redesign"}:
        return run(collect_run_args(first, raw_args[1:]))

    if first == "chat":
        return run_chat(parse_chat_args(raw_args[1:]))
    if first == "history":
        return run_history(parse_history_args(raw_args[1:]))
    if first == "resume":
        chat_cfg = parse_chat_args(["--session", raw_args[1], *raw_args[2:]]) if len(raw_args) > 1 else parse_chat_args(["--session", ""])
        return run_chat(chat_cfg)

    raise SystemExit(f"Unknown command: {first}\nRun `desysflow help` to see available commands.")


if __name__ == "__main__":
    raise SystemExit(main())
