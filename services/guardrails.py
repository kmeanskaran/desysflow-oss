"""Minimal LangChain-compatible secret guardrails.

Wraps any LangChain Runnable/ChatModel so that LLM output is scanned for
secret-like patterns before it propagates downstream.  Uses only
langchain-core primitives (RunnablePassthrough, RunnableCallable) — no
extra guardrail packages required.
"""

from __future__ import annotations

import re
from typing import Any

logger = __import__("logging").getLogger(__name__)

# --------------------------------------------------------------------
# Secret patterns — kept in sync with desysflow_cli/__main__.py
# --------------------------------------------------------------------
_SECRET_PATTERNS: list[str] = [
    r"(?i)\b(password|passwd|pwd|secret|token|api.?key|apikey)\s*[:=]\s*[\"']?[\w\-\.%/@]{4,}[\"']?",
    r"(?i)(mongodb|postgres|mysql|redis|amqp|mssql|oracle)://[^@\s]+:[^@\s]+@",
    r"(?i)\b(AKIA|ABIA|ACMA|ASIA)[0-9A-Z]{16}",
    r"(?i)aws[_\-]?(access[_\-]?key[_\-]?id|secret[_\-]?access[_\-]?key)\s*[:=]\s*\S+",
    r"(?i)amqp[_\-]?(login|password)\s*[:=]\s*\S+",
    r"(?i)(gcp|google)[_\-]?(api[_\-]?key|service[_\-]?account)\s*[:=]\s*\S+",
    r"(?i)azure[_\-]?(subscription|tenant|client)[_\-]?(id|key)\s*[:=]\s*\S+",
    r"(?i)sk_[a-zA-Z0-9]{20,}",
    r"(?i)sk-ant-[a-zA-Z0-9]{20,}",
    r"(?i)ollama[_\-]?(api[_\-]?key)\s*[:=]\s*\S+",
    r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{16,}",
    r"(?i)authorization\s*[:=]\s*(Bearer |Basic )[^\"'}\s]{4,}",
    r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    r"(?i)(slack|github)[_\-]?(token|key|secret)\s*[:=]\s*\S+",
    r"(?i)export\s+(OPENAI_|ANTHROPIC_|AWS_|AZURE_|GCP_|SECRET_|TOKEN_|API_KEY|PASSWORD)",
]


def _compile_secret_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile secret patterns safely even when they contain inline flags."""
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        compiled.append(re.compile(pattern))
    return compiled


_SECRET_RES = _compile_secret_patterns(_SECRET_PATTERNS)
_REDACT_COUNTER = 0


class SecretLeakError(ValueError):
    """Raised when an LLM output contains a detected secret."""

    def __init__(self, redacted_labels: list[str]) -> None:
        self.redacted_labels = redacted_labels
        super().__init__(f"Secret leak detected: {', '.join(redacted_labels)}")


# --------------------------------------------------------------------
# Guardrail runnable — wraps an LLM (or any Runnable) and checks output
# --------------------------------------------------------------------
class _SecretOutputGuardrail:
    """LangChain Runnable that checks LLM output for secrets and raises if found."""

    def __init__(self, wrapped: Any) -> None:
        self.wrapped = wrapped

    def invoke(self, input_: Any, **kwargs: Any) -> Any:
        output = self.wrapped.invoke(input_, **kwargs)
        self._check_output(output)
        return output

    async def ainvoke(self, input_: Any, **kwargs: Any) -> Any:
        output = await self.wrapped.ainvoke(input_, **kwargs)
        self._check_output(output)
        return output

    def _check_output(self, output: Any) -> None:
        global _REDACT_COUNTER
        if output is None:
            return
        text = _extract_text(output)
        if not text:
            return
        redacted: list[str] = []
        for match in _iter_secret_matches(text):
            _REDACT_COUNTER += 1
            label = f"REDACTED-{_REDACT_COUNTER}"
            redacted.append(f"[{label}] {match.group().strip()}")
        if redacted:
            logger.warning("SecretGuardrail: blocked output with %d secret(s)", len(redacted))
            raise SecretLeakError(redacted)


# --------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------

def _extract_text(output: Any) -> str:
    """Coerce a LangChain output object to plain text."""
    if isinstance(output, str):
        return output
    if hasattr(output, "content"):
        return str(output.content)
    if hasattr(output, "text"):
        return str(output.text)
    if hasattr(output, "get"):
        return str(output.get("text", output.get("content", "")))
    return str(output)


def _iter_secret_matches(text: str):
    """Yield all secret matches across compiled patterns."""
    for regex in _SECRET_RES:
        yield from regex.finditer(text)


def _contains_secret(text: str) -> bool:
    return any(regex.search(text) for regex in _SECRET_RES)


def with_secret_guardrail(llm: Any) -> Any:
    """Wrap a LangChain ChatModel / LLM / Runnable so its output is scanned for secrets.

    Usage:
        guarded_llm = with_secret_guardrail(get_llm())
        result = guarded_llm.invoke([("human", "...")])
    """
    return _SecretOutputGuardrail(llm)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Replace secret-like values in *text* with [REDACTED-N] placeholders.

    Returns (scrubbed_text, redacted_labels).
    """
    global _REDACT_COUNTER
    redacted: list[str] = []
    for match in _iter_secret_matches(text):
        _REDACT_COUNTER += 1
        label = f"REDACTED-{_REDACT_COUNTER}"
        redacted.append(f"[{label}] {match.group().strip()}")
        text = text[:match.start()] + f"[{label}]" + text[match.end():]
    return text, redacted


def check_source_for_secrets(source_dir: str, *, max_files: int = 500) -> list[str]:
    """Fast pre-scan of *source_dir* for secret patterns in source files.

    Returns a list of warning strings for files that matched.
    """
    import os
    from pathlib import Path

    warnings: list[str] = []
    scanned = 0
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in {
            ".git", ".venv", "__pycache__", "node_modules",
            "dist", "build", "desysflow",
        }]
        for name in files:
            if scanned >= max_files:
                return warnings
            path = Path(root) / name
            if path.name.startswith("."):
                continue
            try:
                first_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20]
            except Exception:
                continue
            joined = "\n".join(first_lines)
            if _contains_secret(joined):
                warnings.append(f"  {path}: possible secret pattern — review before sharing generated docs")
            scanned += 1
    return warnings
