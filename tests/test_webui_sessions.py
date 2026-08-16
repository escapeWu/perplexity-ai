import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from perplexity.server.webui_sessions import (
    DEFAULT_SESSION_TITLE,
    InvalidWebUISession,
    WebUISessionNotFound,
    WebUISessionStore,
    default_session_database_path,
)


def make_store(tmp_path: Path) -> WebUISessionStore:
    return WebUISessionStore(tmp_path / "sessions.sqlite3")


def test_shared_session_database_env_precedes_legacy_alias(monkeypatch, tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.sqlite3"
    shared_path = tmp_path / "shared.sqlite3"
    monkeypatch.setenv("PPLX_WEBUI_SESSION_DB", str(legacy_path))
    assert default_session_database_path() == legacy_path

    monkeypatch.setenv("PPLX_SESSION_DB", str(shared_path))
    assert default_session_database_path() == shared_path


def test_session_crud_and_restart_persistence(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    first = store.create_session()
    second = store.create_session("Research notes")

    assert first.title == DEFAULT_SESSION_TITLE
    assert second.title == "Research notes"
    assert [session.id for session in store.list_sessions()] == [second.id, first.id]

    renamed = store.rename_session(first.id, "Renamed chat")
    assert renamed.title == "Renamed chat"

    reopened = make_store(tmp_path)
    assert reopened.get_session(first.id).title == "Renamed chat"
    assert {session.id for session in reopened.list_sessions()} == {first.id, second.id}

    reopened.delete_session(second.id)
    with pytest.raises(WebUISessionNotFound):
        reopened.get_session(second.id)


def test_non_webui_sessions_share_storage_but_stay_out_of_sidebar(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    webui_session = store.create_session()
    oai_session = store.create_session(origin="oai")
    mcp_session = store.create_session(origin="mcp")

    assert [session.id for session in store.list_sessions()] == [webui_session.id]
    assert {session.id for session in store.list_sessions(origin=None)} == {
        webui_session.id,
        oai_session.id,
        mcp_session.id,
    }
    assert store.get_session(oai_session.id).origin == "oai"
    assert store.get_session(mcp_session.id).origin == "mcp"


def test_existing_webui_database_migrates_origin_column(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite3"
    session_id = "sess_00000000000000000000000000000000"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE webui_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                title_is_custom INTEGER NOT NULL DEFAULT 0,
                client_id TEXT,
                backend_uuid TEXT,
                attachments_json TEXT NOT NULL DEFAULT '[]',
                model TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO webui_sessions (
                id, title, title_is_custom, attachments_json, created_at, updated_at
            ) VALUES (?, 'Existing chat', 0, '[]', 1, 1)
            """,
            (session_id,),
        )

    store = WebUISessionStore(database_path)

    assert store.get_session(session_id).origin == "webui"
    assert [session.id for session in store.list_sessions()] == [session_id]


def test_bind_client_once_is_immutable_under_concurrency(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda client_id: store.bind_client_once(session.id, client_id),
                [f"account-{index}" for index in range(20)],
            )
        )

    assert len(set(results)) == 1
    assert store.get_session(session.id).client_id == results[0]
    assert store.bind_client_once(session.id, "another-account") == results[0]


def test_commit_turn_persists_safe_history_cursor_and_generated_title(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    store.bind_client_once(session.id, "account-a")

    updated = store.commit_turn(
        session.id,
        user_content=[
            {"type": "text", "text": "Explain native follow-up in detail"},
            {
                "type": "input_file",
                "filename": "notes.txt",
                "file_data": "secret-base64",
                "file_url": "https://private.example/file",
            },
        ],
        assistant_content="It keeps an upstream cursor.",
        sources=[{"title": "Source", "url": "https://example.com"}],
        backend_uuid="backend-1",
        attachments=["https://upstream.example/private-attachment"],
        model="perplexity-search",
    )

    assert updated.title == "Explain native follow-up in detail"
    assert updated.client_id == "account-a"
    assert updated.follow_up() == {
        "backend_uuid": "backend-1",
        "attachments": ["https://upstream.example/private-attachment"],
    }

    messages = store.get_messages(session.id)
    assert messages == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Explain native follow-up in detail"},
                {"type": "input_file", "filename": "notes.txt"},
            ],
            "created_at": messages[0]["created_at"],
        },
        {
            "role": "assistant",
            "content": "It keeps an upstream cursor.",
            "created_at": messages[1]["created_at"],
            "sources": [{"title": "Source", "url": "https://example.com"}],
        },
    ]
    serialized = str(messages)
    assert "secret-base64" not in serialized
    assert "private.example" not in serialized
    assert "upstream.example" not in serialized


def test_custom_title_survives_completed_turn(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session("Pinned title")

    updated = store.commit_turn(
        session.id,
        user_content="A much longer first prompt that would otherwise become the title",
        assistant_content="Answer",
        sources=[],
        backend_uuid="backend-1",
        attachments=[],
        model="perplexity-search",
    )

    assert updated.title == "Pinned title"


def test_invalid_cursor_does_not_persist_an_incomplete_turn(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()

    with pytest.raises(InvalidWebUISession, match="backend_uuid"):
        store.commit_turn(
            session.id,
            user_content="Question",
            assistant_content="Partial answer",
            sources=[],
            backend_uuid="",
            attachments=[],
            model=None,
        )

    assert store.get_messages(session.id) == []
    assert store.get_session(session.id).backend_uuid is None


def test_delete_cascades_messages(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    session = store.create_session()
    store.commit_turn(
        session.id,
        user_content="Question",
        assistant_content="Answer",
        sources=[],
        backend_uuid="backend-1",
        attachments=[],
        model=None,
    )

    store.delete_session(session.id)

    with pytest.raises(WebUISessionNotFound):
        store.get_messages(session.id)


@pytest.mark.parametrize("title", ["", "   ", "x" * 121])
def test_invalid_session_titles_are_rejected(tmp_path: Path, title: str) -> None:
    store = make_store(tmp_path)
    with pytest.raises(InvalidWebUISession):
        store.create_session(title)
