"""SQLite-backed mobile agent conversation thread storage."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any


class MobileAgentThreadStore:
    """Persist per-user mobile chat threads while keeping JSON payload flexible."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def init_db(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.db_path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mobile_agent_threads (
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    preview TEXT DEFAULT '',
                    updated_at INTEGER DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (user_id, thread_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mobile_agent_threads_user_updated "
                "ON mobile_agent_threads(user_id, updated_at DESC)"
            )
            conn.commit()
        finally:
            conn.close()

    def list_threads(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        uid = _clean_user_id(user_id)
        if not uid:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT payload_json FROM mobile_agent_threads
                WHERE user_id=?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (uid, max(1, min(int(limit or 30), 100))),
            ).fetchall()
        finally:
            conn.close()
        return [_decode_payload(row["payload_json"]) for row in rows]

    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any] | None:
        uid = _clean_user_id(user_id)
        tid = _clean_thread_id(thread_id)
        if not uid or not tid:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT payload_json FROM mobile_agent_threads
                WHERE user_id=? AND thread_id=?
                LIMIT 1
                """,
                (uid, tid),
            ).fetchone()
        finally:
            conn.close()
        return _decode_payload(row["payload_json"]) if row else None

    def upsert_thread(self, user_id: str, thread: dict[str, Any]) -> dict[str, Any]:
        uid = _clean_user_id(user_id)
        payload = _normalize_thread(thread)
        tid = payload["id"]
        if not uid:
            raise ValueError("user_id is required")
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO mobile_agent_threads
                    (user_id, thread_id, title, preview, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, thread_id) DO UPDATE SET
                    title=excluded.title,
                    preview=excluded.preview,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    uid,
                    tid,
                    payload.get("title", ""),
                    payload.get("preview", ""),
                    int(payload.get("updatedAt") or 0),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return payload

    def delete_thread(self, user_id: str, thread_id: str) -> bool:
        uid = _clean_user_id(user_id)
        tid = _clean_thread_id(thread_id)
        if not uid or not tid:
            return False
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM mobile_agent_threads WHERE user_id=? AND thread_id=?",
                (uid, tid),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _normalize_thread(thread: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(thread, dict):
        raise ValueError("thread must be an object")
    thread_id = _clean_thread_id(thread.get("id") or thread.get("activeThreadId"))
    if not thread_id:
        raise ValueError("thread id is required")
    messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
    payload = {
        "id": thread_id,
        "title": _trim(thread.get("title") or _thread_title(messages) or "新对话", 80),
        "preview": _trim(thread.get("preview") or _thread_preview(messages) or "继续这个创作上下文", 120),
        "updatedAt": _safe_updated_at(thread.get("updatedAt")),
        "messages": [_safe_message(item) for item in messages[-40:] if isinstance(item, dict)],
        "lastResult": thread.get("lastResult") if isinstance(thread.get("lastResult"), dict) else None,
        "pendingMessageId": _trim(thread.get("pendingMessageId") or "", 120),
        "pendingJobId": _trim(thread.get("pendingJobId") or "", 120),
    }
    return payload


def _decode_payload(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _safe_message(message: dict[str, Any]) -> dict[str, Any]:
    safe = dict(message)
    for key in ("text", "role", "type", "id", "job_id", "jobId", "status", "task_description", "prompt_preview"):
        if key in safe and safe[key] is not None:
            safe[key] = str(safe[key])[:4000]
    return safe


def _thread_title(messages: list[Any]) -> str:
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user" and message.get("text"):
            return str(message.get("text") or "")
    return ""


def _thread_preview(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("text"):
            return str(message.get("text") or "")
    return ""


def _safe_updated_at(value: Any) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = 0
    return parsed if parsed > 0 else int(time.time() * 1000)


def _clean_user_id(value: Any) -> str:
    return _trim(value or "", 160)


def _clean_thread_id(value: Any) -> str:
    return _trim(value or "", 160)


def _trim(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]
