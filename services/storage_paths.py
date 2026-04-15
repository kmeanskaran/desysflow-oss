"""Shared helpers for local DesysFlow storage paths."""

from __future__ import annotations

import os
from pathlib import Path


def get_storage_root() -> Path:
    """Return the local storage root and ensure it exists."""
    raw_root = os.getenv("DESYSFLOW_STORAGE_ROOT", "./desysflow").strip() or "./desysflow"
    root = Path(raw_root).expanduser()
    # Backward-compat: transparently migrate legacy hidden root naming.
    if root.name == ".desflow":
        root = root.with_name(".desysflow")
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_chat_db_path() -> str:
    return str(get_storage_root() / ".desysflow_chat.db")


def default_session_db_path() -> str:
    return str(get_storage_root() / ".desysflow_session.db")
