"""任务验收汇总测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentdesk.config import load_settings
from agentdesk.core.summary import pending_confirmation, task_result
from agentdesk.storage.db import DB


def _db(tmp_path: Path) -> DB:
    settings = load_settings()
    db = DB(db_path=tmp_path / "test.db", settings=settings)
    return db


def _task(db: DB, tmp_path: Path) -> str:
    session = db.create_session()
    task = db.create_task(session.id, "合并表格")
    db.update_task(
        task.id,
        status="done",
        plan_json=json.dumps([{"goal": "合并", "tool": "merge_tables"}]),
        summary="完成，产出 all.csv",
        steps=2,
        cost_yuan=0.0123,
    )
    c1 = db.add_tool_call(task.id, 1, "read_table", {"path": "a.csv"})
    db.update_tool_call(
        c1.id, result={"path": "a.csv", "rows": 3}, status="success", duration_s=0.2
    )
    c2 = db.add_tool_call(task.id, 2, "merge_tables", {"paths": ["a.csv"], "output": "all.csv"})
    db.update_tool_call(
        c2.id,
        result={"path": "all.csv", "output_rows": 3},
        status="success",
        duration_s=0.5,
    )
    return task.id


def test_task_result_structure(tmp_path: Path) -> None:
    db = _db(tmp_path)
    tid = _task(db, tmp_path)
    r = task_result(db, tid)
    assert r["status"] == "done"
    assert r["summary"] == "完成，产出 all.csv"
    assert r["steps"] == 2
    assert r["cost_yuan"] == 0.0123
    assert r["plan"] == [{"goal": "合并", "tool": "merge_tables"}]
    assert len(r["tool_calls"]) == 2
    assert r["tool_calls"][0]["name"] == "read_table"
    assert r["tool_calls"][1]["result"]["output_rows"] == 3


def test_files_deduplicated(tmp_path: Path) -> None:
    db = _db(tmp_path)
    tid = _task(db, tmp_path)
    r = task_result(db, tid)
    assert r["files"] == ["a.csv", "all.csv"]


def test_task_result_unknown_raises(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with pytest.raises(KeyError):
        task_result(db, "nope")


def test_pending_confirmation(tmp_path: Path) -> None:
    db = _db(tmp_path)
    session = db.create_session()
    task = db.create_task(session.id, "覆盖文件")
    db.update_task(task.id, status="waiting_confirm")
    c = db.add_tool_call(task.id, 1, "write_file", {"path": "a.txt", "content": "x"})
    db.update_tool_call(c.id, status="waiting_confirm")
    pending = pending_confirmation(db, task.id)
    assert pending is not None
    assert pending["call_id"] == c.id
    assert pending["name"] == "write_file"
    assert pending["arguments"]["path"] == "a.txt"


def test_pending_confirmation_none(tmp_path: Path) -> None:
    db = _db(tmp_path)
    tid = _task(db, tmp_path)
    assert pending_confirmation(db, tid) is None
    assert pending_confirmation(db, "nope") is None
