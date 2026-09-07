"""Agent 执行循环测试：全流程、确认暂停、四种护栏（步数/重复/成本/取消）。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agentdesk.config import Settings, load_settings
from agentdesk.core.executor import AgentEvent, AgentPaused, AgentRunner
from agentdesk.core.planner import Planner
from agentdesk.llm.client import ChatResult, UsageStats
from agentdesk.storage.db import DB
from agentdesk.tools import build_default_tools
from agentdesk.tools.registry import ToolRegistry

PLAN = json.dumps([{"goal": "查看目录", "tool": "list_files"}], ensure_ascii=False)


class ScriptedLLM:
    """按脚本返回响应的假 LLM，带成本统计与可选延迟。"""

    def __init__(
        self, responses: list[ChatResult], cost_per_call: float = 0.001, delay: float = 0.0
    ) -> None:
        self.responses = list(responses)
        self.cost_per_call = cost_per_call
        self.delay = delay
        self.stats = UsageStats()
        self.calls = 0
        self.last_messages: list[dict] = []

    def chat(self, messages: list, **kwargs: object) -> ChatResult:
        self.calls += 1
        self.last_messages = list(messages)
        self.stats.calls += 1
        self.stats.cost_yuan += self.cost_per_call
        if self.delay:
            time.sleep(self.delay)
        if not self.responses:
            return ChatResult(
                content="任务完成",
                tool_calls=[],
                prompt_tokens=0,
                completion_tokens=0,
                model="fake",
            )
        return self.responses.pop(0)


def _tool_call(name: str, arguments: str = "{}", cid: str = "call_1") -> ChatResult:
    return ChatResult(
        content=None,
        tool_calls=[{"id": cid, "name": name, "arguments": arguments}],
        prompt_tokens=10,
        completion_tokens=5,
        model="fake",
    )


def _text(content: str) -> ChatResult:
    return ChatResult(
        content=content, tool_calls=[], prompt_tokens=10, completion_tokens=5, model="fake"
    )


def _plan_response() -> ChatResult:
    return _text(PLAN)


def _make_env(
    tmp_path: Path,
    responses: list[ChatResult],
    *,
    max_steps: int | None = None,
    max_cost: float | None = None,
    max_repeated: int | None = None,
    max_reflections: int | None = None,
) -> tuple[AgentRunner, list[AgentEvent], DB, Settings]:
    settings = load_settings()
    settings.workspace.root = str(tmp_path)  # 工具工作目录锁定在临时目录
    settings.storage.backups_dir = str(tmp_path / "backups")
    if max_steps is not None:
        settings.agent.max_steps = max_steps
    if max_cost is not None:
        settings.agent.max_cost_yuan = max_cost
    if max_repeated is not None:
        settings.agent.max_repeated_actions = max_repeated
    if max_reflections is not None:
        settings.agent.max_reflections = max_reflections

    db = DB(db_path=tmp_path / "test.db", settings=settings)
    session = db.create_session(workspace=str(tmp_path))
    task = db.create_task(session.id, "测试任务")

    llm = ScriptedLLM(responses)
    events: list[AgentEvent] = []
    runner = AgentRunner(
        task_id=task.id,
        session_id=session.id,
        user_request="测试任务",
        registry=ToolRegistry(build_default_tools()),
        llm=llm,  # type: ignore[arg-type]
        planner=Planner(llm, settings),  # type: ignore[arg-type]
        db=db,
        settings=settings,
        on_event=events.append,
    )
    return runner, events, db, settings


def test_run_completes_with_tool_use(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    runner, events, db, _ = _make_env(
        tmp_path,
        [_plan_response(), _tool_call("list_files"), _text("完成，目录下有 1 个文件 a.txt")],
    )
    task = runner.run()
    assert task.status == "done"
    assert task.steps == 1
    assert "a.txt" in task.summary
    # 事件序列
    types = [e.type for e in events]
    assert "plan" in types
    assert "tool_start" in types
    assert "tool_end" in types
    assert "done" in types
    # DB 记录
    calls = db.list_tool_calls(task.id)
    assert len(calls) == 1
    assert calls[0].name == "list_files"
    assert calls[0].status == "success"


def test_needs_confirmation_pause_and_confirm(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    runner, events, db, _ = _make_env(
        tmp_path,
        [
            _plan_response(),
            _tool_call("write_file", json.dumps({"path": "existing.txt", "content": "new"})),
            _text("已覆盖文件"),
        ],
    )
    with pytest.raises(AgentPaused):
        runner.run()
    task = db.get_task(runner.task_id)
    assert task is not None and task.status == "waiting_confirm"

    confirm_events = [e for e in events if e.type == "needs_confirm"]
    assert len(confirm_events) == 1
    call_id = confirm_events[0].data["call_id"]

    final = runner.confirm(call_id)
    assert final.status == "done"
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "new"
    assert db.get_tool_call(call_id).status == "success"  # type: ignore[union-attr]


def test_confirm_mismatch_raises(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    runner, _, _, _ = _make_env(
        tmp_path,
        [
            _plan_response(),
            _tool_call("write_file", json.dumps({"path": "f.txt", "content": "x"})),
        ],
    )
    with pytest.raises(AgentPaused):
        runner.run()
    with pytest.raises(ValueError, match="不匹配"):
        runner.confirm(9999)


def test_confirmation_after_confirm_does_not_get_stuck(tmp_path: Path) -> None:
    """连续危险操作：确认后再遇到新确认，应再次挂起且不报错不丢 runner。"""
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    runner, events, db, _ = _make_env(
        tmp_path,
        [
            _plan_response(),
            _tool_call("write_file", json.dumps({"path": "existing.txt", "content": "new"})),
            _tool_call("write_file", json.dumps({"path": "keep.txt", "content": "k2"})),
            _text("完成"),
        ],
    )
    # 触发第一次挂起
    with pytest.raises(AgentPaused):
        runner.run()
    assert len([e for e in events if e.type == "needs_confirm"]) == 1
    task = db.get_task(runner.task_id)
    assert task is not None and task.status == "waiting_confirm"

    # 确认后：循环里又遇到新的危险操作 → 二次挂起（而非报错/丢失 runner）
    with pytest.raises(AgentPaused):
        runner.confirm(1)
    task = db.get_task(runner.task_id)
    assert task is not None and task.status == "waiting_confirm"
    confirm_events = [e for e in events if e.type == "needs_confirm"]
    assert len(confirm_events) == 2  # 两次挂起各发一次，无重复
    assert confirm_events[1].data["call_id"] == 2  # 第二次是新的 tool_call

    # 第二次确认后任务正常完成
    final = runner.confirm(2)
    assert final.status == "done"
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "k2"


def test_max_steps_guard(tmp_path: Path) -> None:
    responses = [_plan_response()] + [_tool_call("list_files") for _ in range(5)]
    runner, _, _, _ = _make_env(tmp_path, responses, max_steps=3)
    task = runner.run()
    assert task.status == "stopped"
    assert "最大步数" in task.summary
    assert task.steps == 3


def test_repeat_guard(tmp_path: Path) -> None:
    responses = [
        _plan_response(),
        _tool_call("list_files", "{}", "c1"),
        _tool_call("list_files", "{}", "c2"),
        _tool_call("list_files", "{}", "c3"),
    ]
    runner, _, _, _ = _make_env(tmp_path, responses, max_repeated=2)
    task = runner.run()
    assert task.status == "stopped"
    assert "重复动作" in task.summary


def test_cost_guard(tmp_path: Path) -> None:
    runner, _, _, _ = _make_env(tmp_path, [_plan_response()], max_cost=0.0)
    task = runner.run()
    assert task.status == "stopped"
    assert "成本上限" in task.summary


def test_cancel_guard(tmp_path: Path) -> None:
    responses = [_plan_response()] + [_tool_call("list_files") for _ in range(20)]
    runner, _, _, _ = _make_env(tmp_path, responses, max_steps=50)
    runner.llm.delay = 0.05  # type: ignore[attr-defined]
    result: dict = {}

    def target() -> None:
        result["task"] = runner.run()

    t = threading.Thread(target=target)
    t.start()
    time.sleep(0.3)
    runner.cancel()
    t.join(timeout=10)
    assert not t.is_alive()
    task = result["task"]
    assert task.status == "stopped"
    assert "取消" in task.summary


# ---------- 反思（自检） ----------

def test_reflection_rework_then_pass(tmp_path: Path) -> None:
    """评审发现遗漏→返工→再次产出通过评审→按修改版收尾。"""
    runner, events, db, _ = _make_env(
        tmp_path,
        [
            _plan_response(),  # 计划
            _text("完成，已生成报告。"),  # 第一版产出
            _text('{"verdict": "rework", "issues": "未实际写入文件，需真实产出报告文件"}'),  # 评审1：返工  # noqa: E501
            _text("已补做：写入 report.md。"),  # 修改版
            _text('{"verdict": "pass", "issues": ""}'),  # 评审2：通过
        ],
    )
    task = runner.run()
    assert task.status == "done"
    assert task.summary == "已补做：写入 report.md。"
    # 反思过程对用户可见（message 事件）
    reflects = [
        e.data.get("content", "")
        for e in events
        if e.type == "message" and "[反思]" in e.data.get("content", "")
    ]
    assert any("返工" in r and "未实际写入文件" in r for r in reflects)


def test_reflection_pass_short_circuits(tmp_path: Path) -> None:
    """评审通过时不追加返工指令，直接收尾。"""
    runner, events, _, _ = _make_env(
        tmp_path,
        [
            _plan_response(),
            _text("任务完成。"),
            _text('{"verdict": "pass", "issues": ""}'),
        ],
    )
    task = runner.run()
    assert task.status == "done"
    assert task.summary == "任务完成。"
    # 不应出现返工提示
    reflects = [
        e.data.get("content", "")
        for e in events
        if e.type == "message" and "[反思]" in e.data.get("content", "")
    ]
    assert reflects == []


def test_reflection_disabled_when_zero(tmp_path: Path) -> None:
    """max_reflections=0 时不做评审调用（llm.calls 只含 planner + 主循环各 1 次）。"""
    runner, _, _, settings = _make_env(
        tmp_path, [_plan_response(), _text("直接完成。")], max_reflections=0
    )
    assert settings.agent.max_reflections == 0
    task = runner.run()
    assert task.status == "done"


def test_parse_verdict_tolerant() -> None:
    """verdict 解析容错：裸 JSON / 代码块包裹 / 正则兜底 / 垃圾输入按 pass。"""
    parse = AgentRunner._parse_verdict
    assert parse('{"verdict": "rework", "issues": "缺文件"}') == ("rework", "缺文件")
    fenced = "```json\n" + '{"verdict": "pass", "issues": ""}' + "\n```"
    assert parse(fenced) == ("pass", "")
    assert parse('好的评审如下："verdict":"rework","issues":"x"') == ("rework", "x")
    assert parse("评审完成，没问题") == ("pass", "")


def test_session_memory_carries_previous_task(tmp_path: Path) -> None:
    """同一会话内，第二个任务自动带上第一个任务的结论（会话短期记忆）。"""
    runner1, _, db, _ = _make_env(
        tmp_path, [_plan_response(), _text("完成：已整理出 3 个 csv，报告见 summary.xlsx")]
    )
    t1 = runner1.run()
    assert t1.status == "done"
    session_id = db.get_task(t1.id).session_id  # type: ignore[union-attr]

    # 同会话第二个任务
    t2 = db.create_task(session_id, "第二个任务")
    llm2 = ScriptedLLM([_plan_response(), _text("第二个任务完成")])
    runner2 = AgentRunner(
        task_id=t2.id,
        session_id=session_id,
        user_request="第二个任务",
        registry=runner1.registry,
        llm=llm2,  # type: ignore[arg-type]
        planner=Planner(llm2, settings=runner1.settings),  # type: ignore[arg-type]
        db=db,
        settings=runner1.settings,
    )
    task2 = runner2.run()
    assert task2.status == "done"
    # planner 之后主循环第一轮的 user 消息应含上一任务回顾
    user_msg = next(m for m in llm2.last_messages if m["role"] == "user")
    assert "记忆·本会话上一任务" in user_msg["content"]
    assert "整理出 3 个 csv" in user_msg["content"]


def test_workspace_memory_crosses_sessions(tmp_path: Path) -> None:
    """跨会话记忆：新会话复用同工作区其他会话最近任务的结论，并标注来源。"""
    runner1, _, db, _ = _make_env(
        tmp_path, [_plan_response(), _text("完成：生成了 5 个分节文档")]
    )
    t1 = runner1.run()
    assert t1.status == "done"
    session_a = db.get_task(t1.id).session_id  # type: ignore[union-attr]

    # 新会话 B：同一 workspace、不同 session
    session_b = db.create_session("会话B", workspace=str(tmp_path))
    t2 = db.create_task(session_b.id, "另一个任务")
    llm2 = ScriptedLLM([_plan_response(), _text("任务完成")])
    runner2 = AgentRunner(
        task_id=t2.id,
        session_id=session_b.id,
        user_request="另一个任务",
        registry=runner1.registry,
        llm=llm2,  # type: ignore[arg-type]
        planner=Planner(llm2, settings=runner1.settings),  # type: ignore[arg-type]
        db=db,
        settings=runner1.settings,
    )
    task2 = runner2.run()
    assert task2.status == "done"
    assert session_b.id != session_a
    user_msg = next(m for m in llm2.last_messages if m["role"] == "user")
    assert "记忆·本工作区其他会话" in user_msg["content"]
    assert "生成了 5 个分节文档" in user_msg["content"]


def test_multi_tool_calls_pause_completes_message_chain(tmp_path: Path) -> None:
    """同一批两个工具调用：第一个触发确认时，第二个补"跳过"响应；
    确认后消息链完整（每个 tool_call_id 都有 tool 响应，无占位残留）。"""
    (tmp_path / "existing.txt").write_text("old", encoding="utf-8")
    tc1 = _tool_call(
        "write_file", json.dumps({"path": "existing.txt", "content": "new"}), cid="call_a"
    )
    tc2 = _tool_call("write_file", json.dumps({"path": "other.txt", "content": "x"}), cid="call_b")
    # 把两个 tool_call 放进同一次响应
    tc1.tool_calls = [*tc1.tool_calls, *tc2.tool_calls]  # type: ignore[operator]
    runner, events, db, _ = _make_env(
        tmp_path, [_plan_response(), tc1, _text("完成")]
    )
    with pytest.raises(AgentPaused):
        runner.run()
    call_id = [e for e in events if e.type == "needs_confirm"][0].data["call_id"]
    final = runner.confirm(call_id)
    assert final.status == "done"

    def tool_ids(m: dict) -> list[str]:
        return [c["id"] for c in (m.get("tool_calls") or [])]

    # 每条 assistant 消息的 tool_calls 都必须有对应 tool 响应
    for idx, m in enumerate(runner._messages):  # noqa: SLF001
        ids = tool_ids(m)
        if not ids:
            continue
        followed = [
            t
            for t in runner._messages[idx + 1 :]  # noqa: SLF001
            if t.get("role") == "tool" and t.get("tool_call_id") in ids
        ]
        assert {f["tool_call_id"] for f in followed} == set(ids), f"缺响应: {ids}"
    # 无占位残留
    assert not any(
        m.get("content") == "__PENDING_CONFIRM__" for m in runner._messages  # noqa: SLF001
    )
    # other.txt 被跳过：不应存在
    assert not (tmp_path / "other.txt").exists()
