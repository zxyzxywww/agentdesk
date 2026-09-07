"""评测：反思(Reflection)开关对任务成功率/步数/成本的影响（需真实 API key）。

用法（在 agentdesk 目录，配好 .env）：
    uv run python scripts/bench_reflection.py --tasks 8

说明：
- 每组任务会在独立临时工作目录跑两遍：max_reflections=0(关) 与 =2(开)；
- 每个任务带一个"产出校验函数"，只认真实产物（文件/内容），不认 LLM 自述完成；
- 汇总输出：任务 | 反思关(状态/步数/成本/是否达标) | 反思开(...)；末尾给成功率对比。
- 会调用真实模型产生少量费用（任务数 × 2 次完整执行，建议先 --tasks 4 试跑）。
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile

from agentdesk.config import load_settings
from agentdesk.core.executor import AgentRunner
from agentdesk.core.planner import Planner
from agentdesk.storage.db import DB
from agentdesk.tools import build_default_tools
from agentdesk.tools.registry import ToolRegistry


def _make_case(name: str, request: str, check):
    """(任务名, 用户请求, 校验函数: workspace -> bool)。"""
    return name, request, check


def build_cases():
    def file_created(root: pathlib.Path, rel: str) -> bool:
        return (root / rel).exists()

    def content_has(root: pathlib.Path, rel: str, needle: str) -> bool:
        p = root / rel
        return p.exists() and needle in p.read_text(encoding="utf-8", errors="replace")

    def merged_two(root: pathlib.Path) -> bool:
        out = root / "merged.csv"
        if not out.exists():
            return False
        lines = out.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        return len(lines) == 3  # 表头 + 2 行数据

    return [
        _make_case(
            "写一个报告文件",
            "在工作目录创建 report.md，内容包含一行：已完成。",
            lambda r: content_has(r, "report.md", "已完成"),
        ),
        _make_case(
            "整理散落文件",
            "把工作目录下散落的 .txt 文件按类型归档到 text 子目录（用 organize_by_type）。",
            lambda r: file_created(r, "text/a.txt") and file_created(r, "text/b.txt"),
        ),
        _make_case(
            "合并两个表格",
            "把 data1.csv 与 data2.csv 按列合并成 merged.csv（保留表头）。",
            merged_two,
        ),
        _make_case(
            "写三份分节文档",
            "创建 docs/ 目录并写入 3 个文件：第1节.md/第2节.md/第3节.md，各含一行标题。",
            lambda r: all(file_created(r, f"docs/第{i}节.md") for i in (1, 2, 3)),
        ),
    ]


def run_one(settings, request: str, workspace: pathlib.Path, reflections: int) -> dict:
    settings.agent.max_reflections = reflections
    db = DB(db_path=workspace / "bench.db", settings=settings)
    session = db.create_session(workspace=str(workspace))
    task = db.create_task(session.id, request)
    llm = None
    from agentdesk.llm.client import LLMClient  # 需要 key（.env）

    llm = LLMClient(settings)
    events: list = []
    runner = AgentRunner(
        task_id=task.id,
        session_id=session.id,
        user_request=request,
        registry=ToolRegistry(build_default_tools()),
        llm=llm,
        planner=Planner(llm, settings),
        db=db,
        settings=settings,
        on_event=events.append,
    )
    try:
        rec = runner.run()
        ok = rec.status == "done"
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "steps": -1, "cost": 0.0, "ok": False, "err": str(e)}
    return {"status": rec.status, "steps": rec.steps, "cost": rec.cost_yuan, "ok": ok}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=4)
    args = ap.parse_args()
    settings = load_settings()
    cases = build_cases()[: args.tasks]

    print(f"评测 {len(cases)} 个任务 × 2(反思关/开) ｜ 模型: {settings.model.chat_model}")
    print(f"{'任务':<12} {'关: 状态/步/元/达标':<26} {'开: 状态/步/元/达标'}")
    off_ok = on_ok = 0
    for name, request, check in cases:
        row = {}
        for tag, refl in (("关", 0), ("开", 2)):
            with tempfile.TemporaryDirectory() as td:
                ws = pathlib.Path(td)
                # 准备该任务所需初始文件
                _prepare(ws, name)
                row[tag] = run_one(settings, request, ws, refl)
                row[tag]["达标"] = bool(check(ws))
        off, on = row["关"], row["开"]
        off_ok += 1 if (off["ok"] and off["达标"]) else 0
        on_ok += 1 if (on["ok"] and on["达标"]) else 0
        print(
            f"{name:<12} {off['status']}/{off['steps']}/{off['cost']:.4f}/{off['达标']!s:<5}"
            f" {on['status']}/{on['steps']}/{on['cost']:.4f}/{on['达标']!s}"
        )
    print(f"\n达标率：反思关 {off_ok}/{len(cases)}，反思开 {on_ok}/{len(cases)}")


def _prepare(ws: pathlib.Path, name: str) -> None:
    if name == "整理散落文件":
        (ws / "a.txt").write_text("x", encoding="utf-8")
        (ws / "b.txt").write_text("y", encoding="utf-8")
    elif name == "合并两个表格":
        (ws / "data1.csv").write_text("id,name\n1,a\n", encoding="utf-8")
        (ws / "data2.csv").write_text("id,score\n1,90\n", encoding="utf-8")


if __name__ == "__main__":
    main()
