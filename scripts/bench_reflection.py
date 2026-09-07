"""AgentDesk 评测：对比「反思(Reflection)开关」下的任务效果（需真实 API key）。

产出可直接贴简历/README 的数字：任务完成率、真实产出达标率、
平均步数、平均成本(元)、工具调用成功率、失败恢复次数。

用法（在 agentdesk 目录，配好 .env）：
    uv run python scripts/bench_reflection.py --tasks 8

每组任务在独立临时工作目录跑两遍：max_reflections=0(关) / 2(开)。
每个任务带"产出校验函数"，只认真实产物（文件/内容），不认 LLM 自述完成。
会调用真实模型产生少量费用（任务数 × 2 次完整执行，建议先 --tasks 4 试跑）。
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile

from dotenv import load_dotenv

from agentdesk.config import PROJECT_ROOT, load_settings
from agentdesk.core.executor import AgentPaused, AgentRunner
from agentdesk.core.planner import Planner
from agentdesk.llm.client import LLMClient
from agentdesk.storage.db import DB
from agentdesk.tools import build_default_tools
from agentdesk.tools.registry import ToolRegistry

# ---------- 任务集 ----------

def _make_case(name: str, request: str, check):
    """(任务名, 用户请求, 校验函数: workspace -> bool)。"""
    return name, request, check


def build_cases():
    def exists(root: pathlib.Path, rel: str) -> bool:
        return (root / rel).exists()

    def nonempty(root: pathlib.Path, rel: str) -> bool:
        p = root / rel
        return p.exists() and len(p.read_text(encoding="utf-8", errors="replace").strip()) > 0

    return [
        _make_case(
            "写报告文件",
            "在工作目录创建 report.md，内容包含一行：已完成。",
            lambda r: nonempty(r, "report.md"),
        ),
        _make_case(
            "整理散落文件",
            "把工作目录下散落的 .txt 文件按类型归档到 text 子目录（用 organize_by_type）。",
            lambda r: exists(r, "text/a.txt") and exists(r, "text/b.txt"),
        ),
        _make_case(
            "合并两个表格",
            "把 data1.csv 与 data2.csv 按列合并成 merged.csv（保留表头）。",
            lambda r: (
                exists(r, "merged.csv")
                and len(
                    (r / "merged.csv").read_text(encoding="utf-8").strip().splitlines()
                )
                >= 2
            ),
        ),
        _make_case(
            "写三份分节文档",
            "创建 docs/ 目录并写入 3 个文件：第1节.md/第2节.md/第3节.md，各含一行标题。",
            lambda r: all(exists(r, f"docs/第{i}节.md") for i in (1, 2, 3)),
        ),
        _make_case(
            "统计目录文件",
            "用 count_files 统计工作目录文件数，把结果写入 stats.txt（一行：共N个文件）。",
            lambda r: nonempty(r, "stats.txt"),
        ),
    ]


def _prepare(ws: pathlib.Path, name: str) -> None:
    if name == "整理散落文件":
        (ws / "a.txt").write_text("x", encoding="utf-8")
        (ws / "b.txt").write_text("y", encoding="utf-8")
    elif name == "合并两个表格":
        (ws / "data1.csv").write_text("id,name\n1,a\n", encoding="utf-8")
        (ws / "data2.csv").write_text("id,score\n1,90\n", encoding="utf-8")


# ---------- 单次执行 ----------

def run_one(
    settings, request: str, workspace: pathlib.Path, reflections: int, check
) -> dict:
    settings.agent.max_reflections = reflections
    db = DB(db_path=workspace / "bench.db", settings=settings)
    session = db.create_session(workspace=str(workspace))
    task = db.create_task(session.id, request)
    llm = LLMClient(settings)
    runner = AgentRunner(
        task_id=task.id,
        session_id=session.id,
        user_request=request,
        registry=ToolRegistry(build_default_tools()),
        llm=llm,
        planner=Planner(llm, settings),
        db=db,
        settings=settings,
    )
    out: dict = {
        "steps": 0,
        "cost": 0.0,
        "done": False,
        "meets": False,
        "tools_ok": 0,
        "tools_total": 0,
        "confirms": 0,
    }
    try:
        rec = runner.run()
    except AgentPaused:
        # 无 UI 的评测环境：模拟用户逐次点击"允许"（危险操作自动批准）。
        # 每次批准都计数——该数字本身就是 HITL 安全机制的量化体现。
        while True:
            if runner._pending is None:  # noqa: SLF001
                rec = None
                break
            call_id = runner._pending[3]
            out["confirms"] += 1
            try:
                rec = runner.confirm(call_id)
                break
            except AgentPaused:
                continue
    except Exception as e:  # noqa: BLE001
        rec = None
        out["status"] = "failed"
        out["err"] = str(e)[:120]
    if rec is not None:
        out["status"] = rec.status
        out["steps"] = rec.steps
        out["cost"] = rec.cost_yuan
        out["done"] = rec.status == "done"
    out["meets"] = bool(check(workspace)) if rec is not None else False
    calls = db.list_tool_calls(task.id)
    out["tools_ok"] = sum(1 for c in calls if c.status == "success")
    out["tools_total"] = len(calls)
    return out


# ---------- 汇总 ----------

def _stat(rows: list[dict]) -> dict:
    n = len(rows)
    done = [r for r in rows if r["done"]]
    meets = [r for r in rows if r["meets"]]
    steps = [r["steps"] for r in rows if r["steps"] > 0]
    tools_ok = sum(r["tools_ok"] for r in rows)
    tools_total = sum(r["tools_total"] for r in rows)
    failed_tools = sum(r["tools_total"] - r["tools_ok"] for r in rows)
    recovered = sum(1 for r in rows if r["tools_total"] > r["tools_ok"] and r["done"])
    return {
        "n": n,
        "done": len(done),
        "meets": len(meets),
        "done_rate": len(done) / n if n else 0,
        "meets_rate": len(meets) / n if n else 0,
        "avg_steps": (sum(steps) / len(steps)) if steps else 0,
        "avg_cost": sum(r["cost"] for r in rows) / n if n else 0,
        "tools_rate": tools_ok / tools_total if tools_total else 1.0,
        "failed_tools": failed_tools,
        "recovered": recovered,
        "confirms": sum(r["confirms"] for r in rows),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=4)
    args = ap.parse_args()
    load_dotenv(PROJECT_ROOT / ".env", override=True)  # 评测需真实 API key
    settings = load_settings()
    cases = build_cases()[: args.tasks]

    print(f"评测 {len(cases)} 个任务 ×2（反思关/开） 模型: {settings.model.chat_model}")
    print(f"{'任务':<10} {'状态':<7} {'步数':<5} {'成本(元)':<9} {'工具ok/总':<9} {'达标'}")
    off_rows, on_rows = [], []
    for name, request, check in cases:
        row = {}
        for tag, refl in (("关", 0), ("开", 2)):
            with tempfile.TemporaryDirectory() as td:
                ws = pathlib.Path(td)
                _prepare(ws, name)
                row[tag] = run_one(settings, request, ws, refl, check)
        off_rows.append(row["关"])
        on_rows.append(row["开"])
        for tag in ("关", "开"):
            r = row[tag]
            err = f" err:{r.get('err', '')[:60]}" if not r.get("done") else ""
            print(
                f"{name if tag == '关' else '':<10} "
                f"{r.get('status', 'err')[:7]:<7} {r['steps']:<5} "
                f"{r['cost']:.4f}    {r['tools_ok']}/{r['tools_total']:<7} {r['meets']}{err}"
            )
        print()

    off, on = _stat(off_rows), _stat(on_rows)

    def line(label: str, a: object, b: object) -> None:
        print(f"{label}: 反思关={a} ｜ 反思开={b}")

    print("── 汇总 ──")
    line("任务完成率(done)", f"{off['done_rate']:.0%}", f"{on['done_rate']:.0%}")
    line("产出达标率(真实产物)", f"{off['meets_rate']:.0%}", f"{on['meets_rate']:.0%}")
    line("平均步数", f"{off['avg_steps']:.1f}", f"{on['avg_steps']:.1f}")
    line("平均成本(元)", f"{off['avg_cost']:.4f}", f"{on['avg_cost']:.4f}")
    line("工具调用成功率", f"{off['tools_rate']:.0%}", f"{on['tools_rate']:.0%}")
    line(
        "失败恢复(工具失败但任务完成)",
        f"{off['recovered']}/{off['failed_tools']}",
        f"{on['recovered']}/{on['failed_tools']}",
    )
    line(
        "人工确认次数(危险操作被拦截)",
        off["confirms"],
        on["confirms"],
    )
    fails = [r for r in on_rows if not r.get("done")]
    if fails:
        print("反思开下失败任务：", [r.get("err", "?") for r in fails])


if __name__ == "__main__":
    main()
