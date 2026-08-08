"""任务评估：从 DB 统计成功率/平均步数/平均成本（为简历量化成果准备数字）。"""

from __future__ import annotations

from agentdesk.storage.db import DB


def evaluate_tasks(db: DB) -> dict[str, float | int]:
    """统计全部任务：总数/成功/护栏停止/失败、成功率、平均步数、平均成本。"""
    tasks = db.list_all_tasks()
    total = len(tasks)
    done = [t for t in tasks if t.status == "done"]
    stopped = [t for t in tasks if t.status == "stopped"]
    failed = [t for t in tasks if t.status == "failed"]
    waiting = [t for t in tasks if t.status == "waiting_confirm"]

    avg_steps = sum(t.steps for t in done) / len(done) if done else 0.0
    avg_cost = sum(t.cost_yuan for t in done) / len(done) if done else 0.0
    total_cost = sum(t.cost_yuan for t in tasks)

    return {
        "total": total,
        "done": len(done),
        "stopped": len(stopped),
        "failed": len(failed),
        "waiting_confirm": len(waiting),
        "success_rate": round(len(done) / total, 4) if total else 0.0,
        "avg_steps": round(avg_steps, 2),
        "avg_cost_yuan": round(avg_cost, 4),
        "total_cost_yuan": round(total_cost, 4),
    }
