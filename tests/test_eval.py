"""评估模块测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentdesk.config import load_settings
from agentdesk.core.eval import evaluate_tasks
from agentdesk.storage.db import DB


def _db(tmp_path: Path) -> DB:
    return DB(db_path=tmp_path / "t.db", settings=load_settings())


def test_evaluate_empty() -> None:
    from tempfile import mkdtemp

    db = DB(db_path=Path(mkdtemp()) / "t.db", settings=load_settings())
    r = evaluate_tasks(db)
    assert r["total"] == 0
    assert r["success_rate"] == 0.0


def test_evaluate_mixed(tmp_path: Path) -> None:
    db = _db(tmp_path)
    s = db.create_session()
    t1 = db.create_task(s.id, "任务1")
    db.update_task(t1.id, status="done", steps=3, cost_yuan=0.02)
    t2 = db.create_task(s.id, "任务2")
    db.update_task(t2.id, status="done", steps=5, cost_yuan=0.04)
    t3 = db.create_task(s.id, "任务3")
    db.update_task(t3.id, status="stopped", steps=2, cost_yuan=0.01)
    r = evaluate_tasks(db)
    assert r["total"] == 3
    assert r["done"] == 2
    assert r["stopped"] == 1
    assert r["success_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert r["avg_steps"] == 4.0
    assert r["avg_cost_yuan"] == 0.03
    assert r["total_cost_yuan"] == 0.07
