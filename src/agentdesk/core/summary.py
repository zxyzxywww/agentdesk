"""任务结果汇总与验收：产出清单、结果摘要、计划、工具调用详情。

供 UI 的「任务验收」面板使用：任务结束时展示产出文件、摘要与预览数据，
用户确认后才算完成。
"""

from __future__ import annotations

import json
from typing import Any

from agentdesk.storage.db import DB


def task_result(db: DB, task_id: str) -> dict[str, Any]:
    """汇总任务执行结果。task 不存在时抛 KeyError。"""
    task = db.get_task(task_id)
    if task is None:
        raise KeyError(f"未知任务: {task_id}")

    calls = db.list_tool_calls(task_id)
    tool_calls: list[dict[str, Any]] = []
    files: list[str] = []
    for c in calls:
        try:
            arguments = json.loads(c.arguments_json or "{}")
        except json.JSONDecodeError:
            arguments = {}
        try:
            result = json.loads(c.result_json) if c.result_json else None
        except json.JSONDecodeError:
            result = None
        if c.status == "success" and isinstance(result, dict):
            p = result.get("path")
            if isinstance(p, str) and p and p not in files:
                files.append(p)
        tool_calls.append(
            {
                "name": c.name,
                "status": c.status,
                "duration_s": c.duration_s,
                "arguments": arguments,
                "result": result,
            }
        )

    try:
        plan = json.loads(task.plan_json) if task.plan_json else []
    except json.JSONDecodeError:
        plan = []

    return {
        "id": task.id,
        "user_request": task.user_request,
        "status": task.status,
        "summary": task.summary,
        "steps": task.steps,
        "cost_yuan": task.cost_yuan,
        "plan": plan,
        "files": files,
        "tool_calls": tool_calls,
    }


def pending_confirmation(db: DB, task_id: str) -> dict[str, Any] | None:
    """返回任务中等待确认的工具调用（无则 None）。"""
    task = db.get_task(task_id)
    if task is None:
        return None
    for c in db.list_tool_calls(task_id):
        if c.status == "waiting_confirm":
            try:
                arguments = json.loads(c.arguments_json or "{}")
            except json.JSONDecodeError:
                arguments = {}
            return {"call_id": c.id, "name": c.name, "arguments": arguments}
    return None
