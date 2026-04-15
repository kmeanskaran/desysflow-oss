from pathlib import Path

import pytest

from desysflow_cli.__main__ import _resolve_ollama_model_selection, has_meaningful_source_files


def test_has_meaningful_source_files_ignores_non_source_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("todo", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "diagram.png").write_bytes(b"png")

    assert has_meaningful_source_files(tmp_path) is False


def test_has_meaningful_source_files_accepts_markdown_and_code_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project", encoding="utf-8")
    (tmp_path / "script.sh").write_text("echo hi", encoding="utf-8")

    assert has_meaningful_source_files(tmp_path) is True


def test_resolve_ollama_model_selection_reprompts_when_model_missing(monkeypatch) -> None:
    responses = iter(["missing-model", "y", "gpt-oss:20b-cloud"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    selected = _resolve_ollama_model_selection(
        installed=["gpt-oss:20b-cloud"],
        base_url="http://localhost:11434",
        default="gpt-oss:20b-cloud",
    )

    assert selected == "gpt-oss:20b-cloud"


def test_resolve_ollama_model_selection_aborts_when_user_declines_retry(monkeypatch) -> None:
    responses = iter(["missing-model", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))

    with pytest.raises(SystemExit, match="Aborted"):
        _resolve_ollama_model_selection(
            installed=["gpt-oss:20b-cloud"],
            base_url="http://localhost:11434",
            default="gpt-oss:20b-cloud",
        )
