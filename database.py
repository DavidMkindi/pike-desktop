"""SQLite persistence for chat conversations.

Stored in the per-user data directory so the app works when frozen
into a single executable with PyInstaller.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import config

DB_PATH: Path = config.HISTORY_FILE

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'New conversation',
    messages    TEXT NOT NULL DEFAULT '[]',
    model       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated
    ON conversations(updated_at DESC);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with _connect() as connection:
        connection.executescript(_SCHEMA)


def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
    try:
        messages = json.loads(row["messages"])
    except (ValueError, TypeError):
        messages = []
    preview = ""
    for message in reversed(messages):
        if message.get("role") == "assistant" and message.get("content"):
            preview = message["content"].strip().replace("\n", " ")
            break
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "message_count": len(messages),
        "preview": preview[:140],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_conversations(query: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM conversations"
    params: list[str] = []
    if query:
        sql += " WHERE title LIKE ? OR messages LIKE ?"
        like = f"%{query}%"
        params = [like, like]
    sql += " ORDER BY updated_at DESC LIMIT 200"
    with _connect() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [_row_to_summary(row) for row in rows]


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    if row is None:
        return None
    try:
        messages = json.loads(row["messages"])
    except (ValueError, TypeError):
        messages = []
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "messages": messages,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_conversation(title: str = "New conversation", model: str | None = None) -> dict[str, Any]:
    now = time.time()
    conversation = {
        "id": uuid.uuid4().hex,
        "title": title[:120] or "New conversation",
        "messages": [],
        "model": model,
        "created_at": now,
        "updated_at": now,
    }
    with _connect() as connection:
        connection.execute(
            "INSERT INTO conversations (id, title, messages, model, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation["id"],
                conversation["title"],
                "[]",
                model,
                now,
                now,
            ),
        )
    return conversation


def save_conversation(
    conversation_id: str | None,
    messages: list[dict[str, Any]],
    title: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Insert or update a conversation and return its summary."""
    now = time.time()
    if not conversation_id:
        conversation_id = uuid.uuid4().hex

    existing = get_conversation(conversation_id)
    final_title = (title or (existing or {}).get("title") or "New conversation").strip()

    if final_title in ("", "New conversation"):
        for message in messages:
            if message.get("role") == "user" and message.get("content"):
                text = message["content"].strip().replace("\n", " ")
                final_title = (text[:60] + "…") if len(text) > 60 else text
                break
    final_title = final_title[:120] or "New conversation"

    with _connect() as connection:
        if existing:
            connection.execute(
                "UPDATE conversations SET title = ?, messages = ?, model = ?, updated_at = ?"
                " WHERE id = ?",
                (final_title, json.dumps(messages), model, now, conversation_id),
            )
        else:
            connection.execute(
                "INSERT INTO conversations (id, title, messages, model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, final_title, json.dumps(messages), model, now, now),
            )
    return {
        "id": conversation_id,
        "title": final_title,
        "model": model,
        "updated_at": now,
        "message_count": len(messages),
    }


def rename_conversation(conversation_id: str, title: str) -> bool:
    title = (title or "").strip()[:120] or "New conversation"
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, time.time(), conversation_id),
        )
    return cursor.rowcount > 0


def delete_conversation(conversation_id: str) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
    return cursor.rowcount > 0


def clear_conversations() -> int:
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM conversations")
    return cursor.rowcount