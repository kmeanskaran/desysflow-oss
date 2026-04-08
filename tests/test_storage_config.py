from services.conversation_store import get_conversation_store_config
from services.session_store import get_session_store_config


def test_conversation_store_blank_db_path_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("DESYSFLOW_STORAGE_ROOT", "./tmp-storage")
    monkeypatch.setenv("CHAT_DB_PATH", "")

    cfg = get_conversation_store_config()

    assert cfg.db_path.endswith("tmp-storage/.desysflow_chat.db")
    assert cfg.db_path


def test_session_store_blank_db_path_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("DESYSFLOW_STORAGE_ROOT", "./tmp-storage")
    monkeypatch.setenv("SESSION_DB_PATH", "")

    cfg = get_session_store_config()

    assert cfg.db_path.endswith("tmp-storage/.desysflow_session.db")
    assert cfg.db_path
