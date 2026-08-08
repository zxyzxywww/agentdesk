"""SQLite 存储层测试（临时库文件，不碰真实数据）。"""

from __future__ import annotations

import json
from pathlib import Path

from agentdesk.storage.db import DB, MAX_RESULT_CHARS


def _db(tmp_path: Path) -> DB:
    return DB(db_path=tmp_path / "test.db")


def test_session_crud(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session(title="测试会话", workspace="data/workspace")
    assert s.title == "测试会话"
    assert s.workspace == "data/workspace"

    got = db.get_session(s.id)
    assert got is not None and got.id == s.id

    db.rename_session(s.id, "改名后")
    assert db.get_session(s.id) is not None
    assert db.get_session(s.id).title == "改名后"  # type: ignore[union-attr]

    assert [x.id for x in db.list_sessions()] == [s.id]

    db.delete_session(s.id)
    assert db.get_session(s.id) is None
    assert db.list_sessions() == []


def test_message_roundtrip(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    db.add_message(s.id, "user", "帮我整理文件")
    db.add_message(s.id, "assistant", "好的")
    msgs = db.list_messages(s.id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "帮我整理文件"


def test_task_lifecycle(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    t = db.create_task(s.id, "合并 csv")
    assert t.status == "pending"

    db.update_task(t.id, status="running", steps=3, cost_yuan=0.05)
    t2 = db.get_task(t.id)
    assert t2 is not None
    assert t2.status == "running"
    assert t2.steps == 3
    assert t2.cost_yuan == 0.05

    db.update_task(t.id, status="done", summary="完成，产出 2 个文件")
    t3 = db.get_task(t.id)
    assert t3 is not None and t3.status == "done"
    assert t3.summary == "完成，产出 2 个文件"

    assert [x.id for x in db.list_tasks(s.id)] == [t.id]


def test_tool_call_roundtrip(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    t = db.create_task(s.id, "任务")
    call = db.add_tool_call(t.id, seq=0, name="list_files", arguments={"path": "."})
    assert call.status == "pending"

    db.update_tool_call(
        call.id, result={"files": ["a.csv", "b.csv"]}, status="success", duration_s=0.3
    )
    c2 = db.get_tool_call(call.id)
    assert c2 is not None and c2.status == "success"
    assert c2.duration_s == 0.3
    assert json.loads(c2.result_json) == {"files": ["a.csv", "b.csv"]}

    calls = db.list_tool_calls(t.id)
    assert len(calls) == 1
    assert json.loads(calls[0].arguments_json) == {"path": "."}


def test_tool_call_result_truncated(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    t = db.create_task(s.id, "任务")
    call = db.add_tool_call(t.id, seq=0, name="big", arguments={})
    db.update_tool_call(call.id, result={"data": "x" * (MAX_RESULT_CHARS + 1000)})
    c2 = db.get_tool_call(call.id)
    assert c2 is not None
    assert len(c2.result_json) <= MAX_RESULT_CHARS


def test_delete_session_cascades(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    db.add_message(s.id, "user", "hi")
    t = db.create_task(s.id, "任务")
    db.add_tool_call(t.id, seq=0, name="list_files", arguments={})

    db.delete_session(s.id)
    assert db.list_messages(s.id) == []
    assert db.list_tasks(s.id) == []
    assert db.list_tool_calls(t.id) == []


def test_schema_idempotent(tmp_path: Path) -> None:
    db1 = _db(tmp_path)
    db2 = DB(db_path=tmp_path / "test.db")  # 同一路径重复初始化不报错
    s = db2.create_session()
    assert db1.get_session(s.id) is not None


def test_empty_db_lists(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert db.list_sessions() == []
    assert db.list_messages("nope") == []
    assert db.list_tasks("nope") == []
    assert db.list_tool_calls("nope") == []
    assert db.get_session("nope") is None
    assert db.get_task("nope") is None
