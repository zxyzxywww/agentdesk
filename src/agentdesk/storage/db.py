"""SQLite 存储：会话/消息/任务/工具调用记录。

每个操作使用独立短连接（sqlite 并发安全、零常驻连接管理），
外键约束开启以支持会话级联删除。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentdesk.config import Settings, get_settings

# 工具结果存入 DB 的最大字符数（避免超大结果撑爆数据库）
MAX_RESULT_CHARS = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    workspace TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_request TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    cost_yuan REAL NOT NULL DEFAULT 0,
    steps INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    duration_s REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL DEFAULT '',
    op TEXT NOT NULL,
    src_rel TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    restored INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_toolcalls_task ON tool_calls(task_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Session:
    id: str
    title: str
    workspace: str
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: int
    session_id: str
    role: str
    content: str
    created_at: str


@dataclass
class TaskRecord:
    id: str
    session_id: str
    user_request: str
    status: str
    plan_json: str
    summary: str
    cost_yuan: float
    steps: int
    created_at: str
    updated_at: str


@dataclass
class ToolCallRecord:
    id: int
    task_id: str
    seq: int
    name: str
    arguments_json: str
    result_json: str
    status: str
    duration_s: float
    created_at: str


@dataclass
class BackupRecord:
    id: int
    task_id: str
    op: str
    src_rel: str
    backup_path: str
    restored: int
    created_at: str


class DB:
    """AgentDesk 的 SQLite 数据访问层。"""

    def __init__(self, db_path: str | Path | None = None, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.db_path = Path(db_path) if db_path else settings.db_file
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ---------- sessions ----------

    def create_session(self, title: str = "新会话", workspace: str = "") -> Session:
        sid = _new_id()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (id, title, workspace, created_at, updated_at)"
                " VALUES (?,?,?,?,?)",
                (sid, title, workspace, now, now),
            )
        session = self.get_session(sid)
        assert session is not None
        return session

    def list_sessions(self) -> list[Session]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        return [Session(**dict(r)) for r in rows]

    def get_session(self, session_id: str) -> Session | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return Session(**dict(row)) if row else None

    def rename_session(self, session_id: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, _now(), session_id)
            )

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    # ---------- messages ----------

    def add_message(self, session_id: str, role: str, content: str) -> Message:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
                (session_id, role, content, now),
            )
            mid = cur.lastrowid
            assert mid is not None
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        return Message(id=mid, session_id=session_id, role=role, content=content, created_at=now)

    def list_messages(self, session_id: str) -> list[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        return [Message(**dict(r)) for r in rows]

    # ---------- tasks ----------

    def create_task(
        self, session_id: str, user_request: str, status: str = "pending"
    ) -> TaskRecord:
        tid = _new_id()
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (id, session_id, user_request, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (tid, session_id, user_request, status, now, now),
            )
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        task = self.get_task(tid)
        assert task is not None
        return task

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return TaskRecord(**dict(row)) if row else None

    def list_tasks(self, session_id: str) -> list[TaskRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE session_id=? ORDER BY created_at", (session_id,)
            ).fetchall()
        return [TaskRecord(**dict(r)) for r in rows]

    def list_all_tasks(self) -> list[TaskRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
        return [TaskRecord(**dict(r)) for r in rows]

    def latest_done_task_in_workspace(
        self, workspace: str, exclude_session: str
    ) -> TaskRecord | None:
        """返回该工作区（除指定会话外）最近一条有结论的已完成任务；无则 None。

        供跨会话记忆使用：同一 workspace 的新 session 可复用最近任务的结论。
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT t.* FROM tasks t
                JOIN sessions s ON s.id = t.session_id
                WHERE s.workspace = ? AND t.session_id != ?
                  AND t.status IN ('done', 'stopped') AND trim(t.summary) != ''
                ORDER BY t.updated_at DESC LIMIT 1
                """,
                (workspace, exclude_session),
            ).fetchone()
        return TaskRecord(**dict(row)) if row else None

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        plan_json: str | None = None,
        summary: str | None = None,
        cost_yuan: float | None = None,
        steps: int | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        if status is not None:
            sets.append("status=?")
            vals.append(status)
        if plan_json is not None:
            sets.append("plan_json=?")
            vals.append(plan_json)
        if summary is not None:
            sets.append("summary=?")
            vals.append(summary)
        if cost_yuan is not None:
            sets.append("cost_yuan=?")
            vals.append(cost_yuan)
        if steps is not None:
            sets.append("steps=?")
            vals.append(steps)
        if not sets:
            return
        sets.append("updated_at=?")
        vals.append(_now())
        vals.append(task_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)

    # ---------- tool_calls ----------

    def add_tool_call(
        self, task_id: str, seq: int, name: str, arguments: dict[str, Any]
    ) -> ToolCallRecord:
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO tool_calls (task_id, seq, name, arguments_json, status, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    task_id,
                    seq,
                    name,
                    json.dumps(arguments, ensure_ascii=False),
                    "pending",
                    now,
                ),
            )
            cid = cur.lastrowid
            assert cid is not None
        call = self.get_tool_call(cid)
        assert call is not None
        return call

    def get_tool_call(self, call_id: int) -> ToolCallRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tool_calls WHERE id=?", (call_id,)).fetchone()
        return ToolCallRecord(**dict(row)) if row else None

    def list_tool_calls(self, task_id: str) -> list[ToolCallRecord]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_calls WHERE task_id=? ORDER BY seq", (task_id,)
            ).fetchall()
        return [ToolCallRecord(**dict(r)) for r in rows]

    def update_tool_call(
        self,
        call_id: int,
        *,
        result: Any = None,
        status: str | None = None,
        duration_s: float | None = None,
    ) -> None:
        sets: list[str] = []
        vals: list[Any] = []
        if result is not None:
            sets.append("result_json=?")
            raw = json.dumps(result, ensure_ascii=False, default=str)
            vals.append(raw[:MAX_RESULT_CHARS])
        if status is not None:
            sets.append("status=?")
            vals.append(status)
        if duration_s is not None:
            sets.append("duration_s=?")
            vals.append(duration_s)
        if not sets:
            return
        vals.append(call_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE tool_calls SET {', '.join(sets)} WHERE id=?", vals)

    # ---------- backups ----------

    def add_backup(
        self, *, task_id: str, op: str, src_rel: str, backup_path: str
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO backups (task_id, op, src_rel, backup_path, restored, created_at)"
                " VALUES (?,?,?,?,0,?)",
                (task_id, op, src_rel, backup_path, _now()),
            )
            bid = cur.lastrowid
            assert bid is not None
        return bid

    def get_backup(self, backup_id: int) -> BackupRecord | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM backups WHERE id=?", (backup_id,)
            ).fetchone()
        return BackupRecord(**dict(row)) if row else None

    def list_backups(self, task_id: str | None = None) -> list[BackupRecord]:
        with self._conn() as conn:
            if task_id:
                rows = conn.execute(
                    "SELECT * FROM backups WHERE task_id=? ORDER BY id DESC", (task_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM backups ORDER BY id DESC"
                ).fetchall()
        return [BackupRecord(**dict(r)) for r in rows]

    def mark_restored(self, backup_id: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE backups SET restored=1 WHERE id=?", (backup_id,)
            )
