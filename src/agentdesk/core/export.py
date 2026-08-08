"""会话/任务导出报告（Markdown/HTML），供「一键导出」功能使用。"""

from __future__ import annotations

from agentdesk.storage.db import DB


def export_session_markdown(db: DB, session_id: str) -> str:
    """导出整个会话：消息记录 + 任务记录。"""
    session = db.get_session(session_id)
    if session is None:
        raise KeyError(f"未知会话: {session_id}")
    lines = [f"# 会话：{session.title}", ""]
    for m in db.list_messages(session_id):
        role = "**用户**" if m.role == "user" else "**Agent**"
        lines.append(f"{role}：{m.content}")
        lines.append("")
    tasks = db.list_tasks(session_id)
    if tasks:
        lines.append("## 任务记录")
        for t in tasks:
            lines.append(
                f"- **[{t.status}]** {t.user_request} — {t.summary[:200]}"
                + (f"（{t.cost_yuan:.4f} 元）" if t.cost_yuan else "")
            )
        lines.append("")
    return "\n".join(lines)


def export_task_markdown(db: DB, task_id: str) -> str:
    """导出单个任务：计划、执行过程、产出文件、结果摘要。"""
    from agentdesk.core.summary import task_result

    r = task_result(db, task_id)
    lines = [f"# 任务：{r['user_request'] if 'user_request' in r else r['id']}", ""]
    lines.append(f"- 状态：`{r['status']}`")
    lines.append(f"- 工具步数：{r['steps']}")
    lines.append(f"- 成本：{r['cost_yuan']:.4f} 元")
    lines.append("")
    if r["plan"]:
        lines.append("## 计划")
        for i, s in enumerate(r["plan"], 1):
            lines.append(f"{i}. {s.get('goal', '')}")
        lines.append("")
    lines.append("## 执行过程")
    for c in r["tool_calls"]:
        args = json_dumps(c.get("arguments", {}))
        line = (
            f"- `{c['name']}` **[{c['status']}]** 参数：`{args}`"
            f"（{c['duration_s']:.2f}s）"
        )
        lines.append(line)
    lines.append("")
    if r["files"]:
        lines.append("## 产出文件")
        for f in r["files"]:
            lines.append(f"- `{f}`")
        lines.append("")
    lines.append("## 结果摘要")
    lines.append(r["summary"] or "（无摘要）")
    return "\n".join(lines)


def markdown_to_html(md: str) -> str:
    """Markdown → 独立 HTML 页面。"""
    import markdown as md_lib

    body = md_lib.markdown(md, extensions=["fenced_code", "tables"])
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>AgentDesk 报告</title>"
        "<style>body{max-width:820px;margin:2rem auto;padding:0 1rem;"
        "font-family:system-ui,sans-serif;line-height:1.6;color:#222}"
        "code{background:#f4f4f5;padding:.15rem .3rem;border-radius:4px}"
        "</style></head><body>"
        f"{body}</body></html>"
    )


def json_dumps(obj: object) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:200]
    except (TypeError, ValueError):
        return str(obj)[:200]
