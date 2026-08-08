"""真实冒烟任务：用真实 LLM 跑一组端到端任务并输出评估指标。

用法（需在项目根 .env 配置 DEEPSEEK_API_KEY，搜索可配 TAVILY_API_KEY）：
    uv run python scripts/smoke.py                # 跑全部任务
    uv run python scripts/smoke.py --tasks merge   # 只跑指定任务（merge,organize,research）

任务说明：
    merge     —— 合并工作目录下 3 个示例 csv（验证文件+表格工具链，离线）
    organize  —— 按类型把示例文件归档到子目录（验证移动/建目录，离线）
    research  —— 调研「LLM agent 框架现状」并写带引用的笔记（验证网页调研，需网络）

输出：每个任务的 状态/步数/成本/摘要，以及汇总评估指标。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# 允许直接运行（不依赖安装）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentdesk.config import get_settings  # noqa: E402
from agentdesk.core.eval import evaluate_tasks  # noqa: E402
from agentdesk.core.executor import AgentRunner  # noqa: E402
from agentdesk.core.planner import Planner  # noqa: E402
from agentdesk.llm.client import LLMClient  # noqa: E402
from agentdesk.storage.db import DB  # noqa: E402
from agentdesk.tools import build_default_tools  # noqa: E402
from agentdesk.tools.registry import ToolRegistry  # noqa: E402

CSV_TEMPLATE = "name,score\n张三,{a}\n李四,{b}\n王五,{c}\n"
TASKS = {
    "merge": "把工作目录下所有 csv 文件合并为一个 merged.csv，并汇报总行数",
    "organize": "把工作目录里的文件按类型（csv/txt/md）归档到对应子文件夹",
    "research": (
        "调研一下 LLM agent 框架（如 LangGraph/AutoGen/CrewAI）的现状与差异，"
        "写一份带引用来源的调研笔记"
    ),
}


def prepare_workspace(ws: Path) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (ws / f"data_{i}.csv").write_text(
            CSV_TEMPLATE.format(a=80 + i, b=70 + i, c=90 + i), encoding="utf-8"
        )
    (ws / "notes.txt").write_text("实验记录草稿", encoding="utf-8")
    (ws / "readme.md").write_text("# 说明", encoding="utf-8")


def run_task(
    db: DB,
    settings,
    registry: ToolRegistry,
    llm: LLMClient,
    session_id: str,
    request: str,
) -> dict:
    task = db.create_task(session_id, request)

    def on_event(event) -> None:  # noqa: ANN001
        if event.type in ("tool_start", "tool_end"):
            mark = "→" if event.type == "tool_start" else "✓"
            extra = event.data.get("status", "")
            print(f"    {mark} {event.data.get('name')} {extra}")

    runner = AgentRunner(
        task_id=task.id,
        session_id=session_id,
        user_request=request,
        registry=registry,
        llm=llm,
        planner=Planner(llm, settings),
        db=db,
        settings=settings,
        on_event=on_event,
    )
    try:
        runner.run()
    except Exception as e:  # noqa: BLE001 - 冒烟脚本需要吞掉异常并继续
        print(f"    ⚠ 任务异常: {e}")
    record = db.get_task(task.id)
    assert record is not None
    return record.__dict__


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentDesk 真实冒烟任务")
    parser.add_argument("--tasks", nargs="+", choices=list(TASKS), help="要跑的任务子集")
    args = parser.parse_args()

    settings = get_settings()
    workdir = Path(tempfile.mkdtemp(prefix="agentdesk-smoke-"))
    ws = workdir / "ws"
    prepare_workspace(ws)
    settings.workspace.root = str(ws)
    settings.storage.db_path = str(workdir / "smoke.db")
    settings.storage.backups_dir = str(workdir / "backups")

    db = DB(settings=settings)
    session = db.create_session(title="冒烟任务")
    registry = ToolRegistry(build_default_tools())
    llm = LLMClient(settings)

    print(f"工作目录: {ws}")
    print(f"模型: {settings.model.chat_model} @ {settings.model.base_url}")
    print(f"搜索: {settings.search.provider}")
    print()

    selected = args.tasks or list(TASKS)
    for name in selected:
        print(f"▶ 任务: {name}")
        result = run_task(db, settings, registry, llm, session.id, TASKS[name])
        print(
            f"  状态={result['status']} 步数={result['steps']} "
            f"成本=¥{result['cost_yuan']:.4f}"
        )
        print(f"  摘要: {result['summary'][:120]}")
        print()

    print("========== 评估指标 ==========")
    for k, v in evaluate_tasks(db).items():
        print(f"  {k}: {v}")
    print(f"\n数据库: {db.db_path}")
    print(f"工作目录: {ws}")


if __name__ == "__main__":
    main()
