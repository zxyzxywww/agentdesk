"""导出报告测试。"""

from __future__ import annotations

import json
from pathlib import Path

from agentdesk.config import load_settings
from agentdesk.core.export import (
    export_session_markdown,
    export_task_markdown,
    markdown_to_html,
)
from agentdesk.storage.db import DB


def _db(tmp_path: Path) -> DB:
    return DB(db_path=tmp_path / "t.db", settings=load_settings())


def test_export_session_markdown(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session(title="我的会话")
    db.add_message(s.id, "user", "帮我整理文件")
    db.add_message(s.id, "assistant", "已完成")
    t = db.create_task(s.id, "整理文件")
    db.update_task(t.id, status="done", summary="产出 3 个文件", cost_yuan=0.01)
    md = export_session_markdown(db, s.id)
    assert "# 会话：我的会话" in md
    assert "**用户**：帮我整理文件" in md
    assert "**Agent**：已完成" in md
    assert "任务记录" in md and "产出 3 个文件" in md


def test_export_task_markdown(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    t = db.create_task(s.id, "合并 csv")
    db.update_task(
        t.id,
        status="done",
        plan_json=json.dumps([{"goal": "合并", "tool": "merge_tables"}]),
        summary="完成，产出 all.csv",
        steps=2,
        cost_yuan=0.0123,
    )
    c = db.add_tool_call(t.id, 1, "merge_tables", {"paths": ["a.csv"], "output": "all.csv"})
    db.update_tool_call(c.id, result={"path": "all.csv"}, status="success", duration_s=0.5)
    md = export_task_markdown(db, t.id)
    assert "合并 csv" in md
    assert "`merge_tables`" in md
    assert "all.csv" in md
    assert "0.0123" in md


def test_export_unknown_raises(tmp_path: Path) -> None:
    db = _db(tmp_path)
    import pytest

    with pytest.raises(KeyError):
        export_session_markdown(db, "nope")


def test_markdown_to_html(tmp_path: Path) -> None:
    html = markdown_to_html("# 标题\n\n正文")
    assert "<html>" in html and "<h1>" in html and "正文" in html
