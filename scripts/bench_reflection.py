"""AgentDesk 对照评测：8 类代表性任务 × Reflection 开关 × 重复轮次（需真实 API key）。

设计原则（冻结契约，跑完不改题）：
- 每任务固化：输入话术 / 预置文件 / 预期产物 / 成功判定（只认真实文件与内容，不认 LLM 自述）；
- 反思语义：关 = max_reflections=0（无返工机会）；开 = max_reflections=2（≤2 轮返工）；
- HITL：危险操作在 headless 下模拟用户逐次批准并计数（7 类任务会触发确认）；
- 状态库放工作区外（生产同构：db 在 data/db），工作区只放用户文件。

产出（面试口径）："8 类代表性任务、48 次真实执行（2 条件 × 3 重复）的对照实验，
对比 Reflection 开关下的完成率、产物达标率、首轮通过率、返工次数、步数、成本与耗时。"

用法：
    uv run python scripts/bench_reflection.py --tasks 8 --repeat 3
费用：DeepSeek 实测约 元0.02~0.07/次 → 48 次约 元2~3（先 --tasks 2 --repeat 1 冒烟）。
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile
import time

from dotenv import load_dotenv

from agentdesk.config import PROJECT_ROOT, load_settings
from agentdesk.core.executor import AgentPaused, AgentRunner
from agentdesk.core.planner import Planner
from agentdesk.llm.client import LLMClient
from agentdesk.storage.db import DB
from agentdesk.tools import build_default_tools
from agentdesk.tools.registry import ToolRegistry

# ---------- 任务契约（冻结；每个任务= 输入/预置/成功判定） ----------


def _exists(root: pathlib.Path, rel: str) -> bool:
    return (root / rel).exists()


def _nonempty(root: pathlib.Path, rel: str) -> bool:
    p = root / rel
    return p.exists() and len(p.read_text(encoding="utf-8", errors="replace").strip()) > 0


def build_cases():
    """返回 [(名称, 输入话术, 预置函数, 成功判定函数)]，判定只认真实产物。"""
    return [
        # 1. write_file 单点产出
        ("写报告文件",
         "请创建文件 report.md，内容为一行文字：已完成。（直接放在当前目录根下，不要建子目录）",
         lambda ws: None,
         lambda ws: _nonempty(ws, "report.md")),
        # 2. organize_by_type + 归档确认
        ("整理散落文件",
         "请把当前目录下的 a.txt 和 b.txt 移动到 text/ 子目录里（先创建 text 目录）。",
         lambda ws: [ (ws / n).write_text("x", encoding="utf-8") for n in ("a.txt", "b.txt") ],
         lambda ws: _exists(ws, "text/a.txt") and _exists(ws, "text/b.txt")),
        # 3. read_table/merge_tables/describe 链式数据任务
        ("合并两个表格",
         "把当前目录下的 data1.csv 与 data2.csv 按列合并成一个 merged.csv"
         "（保留表头，结果直接放在当前目录）。",
         lambda ws: [
             (ws / "data1.csv").write_text("id,name\n1,a\n", encoding="utf-8"),
             (ws / "data2.csv").write_text("id,score\n1,90\n", encoding="utf-8"),
         ],
         lambda ws: _exists(ws, "merged.csv")
         and len((ws / "merged.csv").read_text(encoding="utf-8").strip().splitlines()) >= 2),
        # 4. 多文件批量产出
        ("写三份分节文档",
         "创建 docs/ 子目录并写入 3 个文件：第1节.md/第2节.md/第3节.md，各含一行标题。",
         lambda ws: None,
         lambda ws: all(_exists(ws, f"docs/第{i}节.md") for i in (1, 2, 3))),
        # 5. count_files 统计
        ("统计目录文件",
         "用 count_files 统计当前目录文件数，把结果写入当前目录下的 stats.txt"
         "（内容写一行：共N个文件）。",
         lambda ws: (ws / "t1.csv").write_text("a,b\n", encoding="utf-8"),
         lambda ws: _nonempty(ws, "stats.txt")),
        # 6. knowledge_search 本地检索 + 引用写笔记（防编造）
        ("本地检索引用笔记",
         "先在当前目录的 技术笔记.md 里用 knowledge_search 检索 RAG 相关内容，"
         "再写一份 note.md，引用原文里的关键词并标注来源行号。",
         lambda ws: (ws / "技术笔记.md").write_text(
             "# 笔记\n\n## RAG\nRAG 是检索增强生成，把向量检索结果拼进提示词。\n",
             encoding="utf-8"),
         lambda ws: _nonempty(ws, "note.md")
         and "RAG" in (ws / "note.md").read_text(encoding="utf-8")),
        # 7. 覆盖已有文件 → HITL 确认（headless 自动批准并计数）
        ("覆盖已有文件",
         "请把 summary.txt 的内容覆盖重写为：目录状态已更新。（原文件已存在，属危险操作）",
         lambda ws: (ws / "summary.txt").write_text("旧内容", encoding="utf-8"),
         lambda ws: (ws / "summary.txt").exists()
         and "目录状态已更新" in (ws / "summary.txt").read_text(encoding="utf-8")),
        # 8. 混合类型多步编排 + 清理报告
        ("混合多步编排",
         "检查当前目录中的 alpha.csv / beta.txt / gamma.log，按类型归档整理，"
         "最后写 cleanup_report.md 说明整理结果。",
         lambda ws: [
             (ws / "alpha.csv").write_text("id,v\n1,2\n", encoding="utf-8"),
             (ws / "beta.txt").write_text("x", encoding="utf-8"),
             (ws / "gamma.log").write_text("2026-01-01 ok\n", encoding="utf-8"),
         ],
         lambda ws: _nonempty(ws, "cleanup_report.md")
         and not all(_exists(ws, n) for n in ("alpha.csv", "beta.txt", "gamma.log"))),
        # 9. 多约束审计报告（易遗漏项 → 反思返工最可能触发的场景）
        ("审计报告多约束",
         "检查当前目录所有文件，生成 audit.md 审计报告。报告必须包含四个小节"
         "（依次为：## 文件统计 / ## 问题清单 / ## 整理建议 / ## 结论）："
         "文件统计要写全每类文件数量；问题清单必须列出至少 3 个具体问题；"
         "整理建议要按优先级排序。写完后对照要求自查：四节是否齐全、问题是否够 3 个，"
         "不齐就补充后再交付。",
         lambda ws: [
             (ws / "data.csv").write_text("id,value\n1,10\n1,10\n2,20\n", encoding="utf-8"),
             (ws / "notes.txt").write_text("随手记录，无日期无作者。\n", encoding="utf-8"),
             (ws / "old.log").write_text("no timestamp line\nsecond line\n", encoding="utf-8"),
         ],
         lambda ws: _nonempty(ws, "audit.md")
         and all(k in (ws / "audit.md").read_text(encoding="utf-8")
                 for k in ("文件统计", "问题清单", "整理建议"))),
        # 10. 清单逐条核对（要求不漏项不合并）
        ("清单逐条核对",
         "当前目录的 spec.md 列出 5 条验收要求。请逐条检查并写 result.md："
         "每条要求分别给『达成』或『未达成』并附一句依据，5 条必须逐条列出、不得遗漏或合并。",
         lambda ws: [
             (ws / "spec.md").write_text(
                 "1. 存在 report.md\n2. report.md 内含'结论'\n"
                 "3. 存在 data.csv\n4. data.csv 至少 2 行\n5. 存在 notes.txt\n",
                 encoding="utf-8"),
             (ws / "report.md").write_text("# r\n\n结论：ok\n", encoding="utf-8"),
             (ws / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8"),
         ],
         lambda ws: _nonempty(ws, "result.md")
         and "达成" in (ws / "result.md").read_text(encoding="utf-8")),
    ]


# ---------- 单次执行 ----------

def run_one(settings, request: str, workspace: pathlib.Path, reflections: int, check) -> dict:
    settings.agent.max_reflections = reflections
    settings.workspace.root = str(workspace)  # 每个任务独立工作目录
    state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bench-state-"))
    db = DB(db_path=state_dir / "state.db", settings=settings)
    session = db.create_session(workspace=str(workspace))
    task = db.create_task(session.id, request)
    llm = LLMClient(settings)
    reworks: list[str] = []
    runner = AgentRunner(
        task_id=task.id,
        session_id=session.id,
        user_request=request,
        registry=ToolRegistry(build_default_tools()),
        llm=llm,
        planner=Planner(llm, settings),
        db=db,
        settings=settings,
        on_event=lambda e: reworks.append(e.data.get("content", ""))
        if e.type == "message" and str(e.data.get("content", "")).startswith("[反思]")
        else None,
    )
    out: dict = {
        "steps": 0, "cost": 0.0, "done": False, "meets": False,
        "tools_ok": 0, "tools_total": 0, "confirms": 0, "reworks": 0, "dur": 0.0,
    }
    t0 = time.perf_counter()
    try:
        rec = runner.run()
    except AgentPaused:
        while True:  # headless：模拟用户逐次批准危险操作并计数
            if runner._pending is None:  # noqa: SLF001
                rec = None
                break
            out["confirms"] += 1
            try:
                rec = runner.confirm(runner._pending[3])  # noqa: SLF001
                break
            except AgentPaused:
                continue
    except Exception as e:  # noqa: BLE001
        rec = None
        out["err"] = str(e)[:120]
    out["dur"] = time.perf_counter() - t0
    if rec is not None:
        out["status"] = rec.status
        out["steps"] = rec.steps
        out["cost"] = rec.cost_yuan
        out["done"] = rec.status == "done"
    out["meets"] = bool(check(workspace)) if rec is not None else False
    out["reworks"] = len(reworks)
    calls = db.list_tool_calls(task.id)
    out["tools_ok"] = sum(1 for c in calls if c.status == "success")
    out["tools_total"] = len(calls)
    return out


# ---------- 汇总 ----------

def _stat(rows: list[dict]) -> dict:
    n = len(rows)
    done = [r for r in rows if r["done"]]
    meets = [r for r in rows if r["meets"]]
    first_pass = [r for r in rows if r["meets"] and r["reworks"] == 0]
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
        "first_pass_rate": len(first_pass) / n if n else 0,
        "reworks": sum(r["reworks"] for r in rows),
        "avg_reworks": sum(r["reworks"] for r in rows) / n if n else 0,
        "avg_steps": (sum(steps) / len(steps)) if steps else 0,
        "avg_cost": sum(r["cost"] for r in rows) / n if n else 0,
        "avg_dur": sum(r["dur"] for r in rows) / n if n else 0,
        "tools_rate": tools_ok / tools_total if tools_total else 1.0,
        "failed_tools": failed_tools,
        "recovered": recovered,
        "confirms": sum(r["confirms"] for r in rows),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=8)
    ap.add_argument("--skip", type=int, default=0, help="跳过前 N 个任务（与 --tasks 配合切片）")
    ap.add_argument("--repeat", type=int, default=1, help="每条件重复次数（默认 1）")
    ap.add_argument(
        "--out", default=None,
        help="额外把完整输出写入该文件（建议 Windows 绝对路径，避免跨 shell /tmp 丢失）",
    )
    args = ap.parse_args()
    if args.out:
        import sys

        class _Tee:  # noqa: N801
            def __init__(self, orig, f):
                self._orig = orig
                self._f = f

            def write(self, s):
                try:
                    self._orig.write(s)
                except UnicodeEncodeError:
                    pass  # 终端编码容不下时丢弃显示，不影响文件输出
                self._f.write(s)

            def flush(self):
                self._orig.flush()
                self._f.flush()

        sys.stdout = _Tee(sys.stdout, open(args.out, "w", encoding="utf-8", newline="\n"))
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    settings = load_settings()
    cases = build_cases()[args.skip : args.tasks]
    total = len(cases) * 2 * args.repeat
    print(
        f"评测 {len(cases)} 任务 × 2 条件 × {args.repeat} 重复 = {total} 次执行 "
        f"｜ 模型: {settings.model.chat_model}"
    )
    off_rows: list[dict] = []
    on_rows: list[dict] = []
    for name, request, prepare, check in cases:
        print(f"\n── {name} ──")
        for rep in range(args.repeat):
            row: dict = {}
            for tag, refl in (("关", 0), ("开", 2)):
                with tempfile.TemporaryDirectory() as td:
                    ws = pathlib.Path(td)
                    prepare(ws)
                    row[tag] = run_one(settings, request, ws, refl, check)
            off_rows.append(row["关"])
            on_rows.append(row["开"])
            r1, r2 = row["关"], row["开"]
            print(
                f"  r{rep + 1}: 关 {r1.get('status', 'err')[:6]}/{r1['steps']}步/"
                f"元{r1['cost']:.3f}/达{r1['meets']}"
                f"  | 开 {r2.get('status', 'err')[:6]}/{r2['steps']}步/"
                f"元{r2['cost']:.3f}/达{r2['meets']}/返工{r2['reworks']}"
            )

    off, on = _stat(off_rows), _stat(on_rows)

    def line(label: str, a: object, b: object) -> None:
        print(f"{label}: 反思关={a} ｜ 反思开={b}")

    print("\n── 汇总 ──")
    line("执行次数", off["n"], on["n"])
    line("任务完成率(done)", f"{off['done_rate']:.0%}", f"{on['done_rate']:.0%}")
    line("产物达标率(真实文件)", f"{off['meets_rate']:.0%}", f"{on['meets_rate']:.0%}")
    line(
        "首轮直接通过率(无返工即达标)",
        f"{off['first_pass_rate']:.0%}",
        f"{on['first_pass_rate']:.0%}",
    )
    line("平均返工次数", "-", f"{on['avg_reworks']:.2f}")
    line("平均步数", f"{off['avg_steps']:.1f}", f"{on['avg_steps']:.1f}")
    line("平均成本(元)", f"{off['avg_cost']:.4f}", f"{on['avg_cost']:.4f}")
    line("平均耗时(秒)", f"{off['avg_dur']:.0f}", f"{on['avg_dur']:.0f}")
    line("工具调用成功率", f"{off['tools_rate']:.0%}", f"{on['tools_rate']:.0%}")
    line(
        "失败恢复(工具失败但完成)",
        f"{off['recovered']}/{off['failed_tools']}",
        f"{on['recovered']}/{on['failed_tools']}",
    )
    line("人工确认次数(HITL)", off["confirms"], on["confirms"])
    fails = [r for r in on_rows if not r.get("done")]
    if fails:
        print("反思开失败样本：", [r.get("err", "?")[:60] for r in fails])


if __name__ == "__main__":
    main()
