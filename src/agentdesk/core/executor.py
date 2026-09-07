"""Agent 执行循环（ReAct）与护栏。

流程：
1. Planner 生成初始计划 → 存入任务；
2. 循环：LLM 决策（文本或工具调用）→ 执行工具 → 结果回填 → 护栏检查；
3. 工具需用户确认时抛 AgentPaused 暂停，等待 confirm() 后继续；
4. 护栏：最大步数 / 成本上限 / 重复动作 / 用户取消 / 路径穿越（工具层）。

事件回调（on_event）把执行过程推送给 UI，实现实时工具状态流。
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from agentdesk.config import Settings
from agentdesk.core.planner import Planner, PlanStep
from agentdesk.llm.client import LLMClient
from agentdesk.storage.db import DB, TaskRecord
from agentdesk.tools.registry import (
    NeedsConfirmation,
    ToolContext,
    ToolRegistry,
    ToolResult,
    arg_error,
)

SYSTEM_PROMPT = """你是 AgentDesk，一个运行在用户本地数据目录中的任务型智能体。

规则：
1. 使用中文与用户交流；需要操作文件/数据时调用工具。
2. 所有路径都是相对工作目录的相对路径。
3. 【优先用内置工具，能批量就批量】读取/合并/统计表格用 read_table/merge_tables/describe_table；
   【按类型归档用 organize_by_type 一次完成】；创建目录用 make_dir 一次传多个 paths；
   只有内置工具无法完成时才用 run_python 编写脚本（脚本是危险操作，需用户确认，能不用就不要用）。
4. 删除、覆盖、执行代码等危险操作会自动请求用户确认；确认后继续。
5. 网页调研时优先引用近 1~2 年的资料，并在笔记中标注来源与时间；不要编造来源。
6. 每完成关键步骤尽量用 list_files / read_table 验证产出。
7. 任务完成后，用一段话总结：做了什么、产出文件在哪、结果如何。
8. 不要编造文件或结果；一切以工具返回为准。
9. 引用本地文档/笔记内容前先调用 knowledge_search 检索，禁止凭记忆编造来源。
10. 初始计划只是建议：发现需求变化或步骤不适用时可调用 update_plan 更新剩余计划。"""

MAX_HISTORY_MESSAGES = 40

# 反思（自检）评审者提示词：检查最终产出是否真正完成任务，要求结构化输出便于解析
REFLECT_PROMPT = (
    "你是评审者。请检查执行者刚才的最终产出是否真正完成了用户任务，"
    '而不是只看它自己说"完成"。\n'
    "\n"
    "判断标准：\n"
    "1. 任务的每个要求是否都被满足（多个文件/指定格式/指定输出位置等），有无遗漏；\n"
    "2. 产出是否基于工具的真实返回（有没有编造文件、数据或来源）；\n"
    "3. 有无明显硬伤或低成本即可修正的错误。\n"
    "\n"
    "请只输出一个 JSON 对象（不要输出其它文字），格式：\n"
    '{"verdict": "pass 或 rework", "issues": "rework 时用一句话说明最关键的问题；'
    'pass 时为空字符串"}'
)


class AgentPaused(Exception):
    """任务因需用户确认而暂停。"""

    def __init__(self, call_id: int, reason: str) -> None:
        super().__init__(reason)
        self.call_id = call_id
        self.reason = reason


@dataclass
class AgentEvent:
    """推送给 UI 的执行事件。"""

    type: str  # plan | tool_start | tool_end | message | needs_confirm | done | stopped | error | cancelled  # noqa: E501
    task_id: str
    data: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[AgentEvent], None]


class AgentRunner:
    """单个任务的执行器。run() 阻塞直到任务完成/暂停/取消。"""

    def __init__(
        self,
        *,
        task_id: str,
        session_id: str,
        user_request: str,
        registry: ToolRegistry,
        llm: LLMClient,
        planner: Planner,
        db: DB,
        settings: Settings,
        on_event: EventCallback | None = None,
    ) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.user_request = user_request
        self.registry = registry
        self.llm = llm
        self.planner = planner
        self.db = db
        self.settings = settings
        self.on_event = on_event

        self.cancel_event = threading.Event()
        self._messages: list[dict[str, Any]] = []
        self._tool_steps = 0
        self._recent_calls: list[tuple[str, str]] = []
        # 待确认的调用：(name, args, seq, db_call_id, tool_call_id)
        self._pending: tuple[str, dict, int, int, str] | None = None
        self._plan: list[PlanStep] = []
        self._stop_reason: str | None = None
        self._reflection_rounds = 0
        self._history_context = ""
        self.final_summary = ""

    # ---------- 事件 ----------

    def _emit(self, etype: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(AgentEvent(type=etype, task_id=self.task_id, data=data))

    def _hang(self, pause: AgentPaused) -> None:
        """任务进入等待确认的挂起态：更新状态并通知 UI。"""
        self.db.update_task(self.task_id, status="waiting_confirm")
        self._emit("needs_confirm", call_id=pause.call_id, reason=pause.reason)

    def _fail(self, e: Exception) -> None:
        """任务失败：更新状态并通知 UI。"""
        self.db.update_task(self.task_id, status="failed", summary=f"任务失败: {e}")
        self._emit("error", error=str(e))

    def _loop_then_finish(self) -> TaskRecord:
        """执行循环并收尾；若再次需确认则抛 AgentPaused（由调用方挂起一次）。"""
        self._loop()
        status = "stopped" if self._stop_reason else "done"
        return self._finish(status)

    # ---------- 主流程 ----------

    def run(self) -> TaskRecord:
        """阻塞执行任务。需确认时抛 AgentPaused（任务状态 waiting_confirm）。"""
        self.db.update_task(self.task_id, status="running")
        # 会话记忆：把本会话最近一次已完成任务的结论带给新任务（联系上下文）
        for prev in reversed(self.db.list_tasks(self.session_id)):
            if prev.id != self.task_id and prev.status in ("done", "stopped") and prev.summary:
                self._history_context = prev.summary[:400]
                break
        self.db.add_message(self.session_id, "user", self.user_request)
        try:
            self._plan = self.planner.plan(self.user_request, self.registry.openai_schema())
            plan_json = json.dumps(
                [s.model_dump() for s in self._plan], ensure_ascii=False
            )
            self.db.update_task(self.task_id, plan_json=plan_json)
            self._emit("plan", plan=[s.model_dump() for s in self._plan])

            self._messages = self._initial_messages()
            return self._loop_then_finish()
        except AgentPaused as pause:
            self._hang(pause)
            raise
        except Exception as e:  # noqa: BLE001 - 兜底：任何异常都记录为失败
            self._fail(e)
            raise

    def confirm(self, call_id: int) -> TaskRecord:
        """用户确认后，重新执行待确认调用并继续任务（阻塞直到结束）。"""
        if self._pending is None:
            raise RuntimeError("没有待确认的操作")
        name, args, seq, db_call_id, tool_call_id = self._pending
        if db_call_id != call_id:
            raise ValueError(f"call_id 不匹配: {call_id}")
        self._pending = None
        ctx = ToolContext(
            self.settings.workspace_root,
            self.settings,
            confirmed=True,
            db=self.db,
            task_id=self.task_id,
            update_plan=self._update_plan_from_tool,
        )
        self._execute_tool_call(name, args, seq, ctx, tool_call_id, existing_call_id=db_call_id)
        try:
            return self._loop_then_finish()
        except AgentPaused as pause:
            # 确认后又遇到新的危险操作：转入挂起态（并通知 UI 再次确认）
            self._hang(pause)
            raise

    def reject(self, call_id: int) -> TaskRecord:
        """用户拒绝该操作：记录为失败并提示模型调整方案，继续任务（阻塞直到结束）。"""
        if self._pending is None:
            raise RuntimeError("没有待确认的操作")
        name, args, seq, db_call_id, tool_call_id = self._pending
        if db_call_id != call_id:
            raise ValueError(f"call_id 不匹配: {call_id}")
        self._pending = None
        self.db.update_tool_call(
            call_id, result={"rejected": True, "operation": name}, status="failed"
        )
        self._emit(
            "tool_end",
            name=name,
            status="failed",
            summary="用户拒绝了该操作",
            seq=seq,
        )
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": "用户拒绝了该操作。请调整方案，不要重复请求同一个操作。",
            }
        )
        try:
            return self._loop_then_finish()
        except AgentPaused as pause:
            self._hang(pause)
            raise

    def cancel(self) -> None:
        """请求中断（UI 停止按钮调用）。"""
        self.cancel_event.set()

    # ---------- 内部 ----------

    def _initial_messages(self) -> list[dict[str, Any]]:
        plan_text = "\n".join(f"{i + 1}. {s.goal}" for i, s in enumerate(self._plan))
        parts = [f"任务：{self.user_request}"]
        if self._history_context:
            parts.append(f"\n\n（本会话上一任务的回顾：{self._history_context}）")
        parts.append(f"\n\n初步计划：\n{plan_text or '（未生成）'}")
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "".join(parts)},
        ]

    def _loop(self) -> None:
        while True:
            reason = self._check_guards()
            if reason:
                self._stop_reason = reason
                self.final_summary = f"任务终止：{reason}"
                self._emit("message", content=f"[系统] {reason}")
                return
            result = self.llm.chat(
                messages=self._trimmed(), tools=self.registry.openai_schema()
            )
            self._messages.append(
                {
                    "role": "assistant",
                    "content": result.content or "",
                    "tool_calls": self._tool_call_dicts(result.tool_calls),
                }
            )
            if not result.tool_calls:
                if self._maybe_reflect():
                    self.final_summary = result.content or "任务完成"
                    self._emit("message", content=self.final_summary)
                    return
                # 评审要求返工：进入下一轮循环，让模型按意见修正（可继续调工具）
                continue
            for seq, tc in enumerate(result.tool_calls, start=self._tool_steps + 1):
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    if not isinstance(args, dict):
                        raise ValueError("参数必须是对象")
                except (json.JSONDecodeError, ValueError):
                    self._append_tool_feedback(
                        tc["id"], f"参数 JSON 解析失败: {tc['arguments'][:200]}"
                    )
                    continue
                ctx = ToolContext(
                    self.settings.workspace_root,
                    self.settings,
                    confirmed=False,
                    db=self.db,
                    task_id=self.task_id,
                    update_plan=self._update_plan_from_tool,
                )
                self._execute_tool_call(tc["name"], args, seq, ctx, tc["id"])

    def _execute_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        seq: int,
        ctx: ToolContext,
        tool_call_id: str,
        existing_call_id: int | None = None,
    ) -> None:
        self._emit("tool_start", name=name, args=args, seq=seq)
        if existing_call_id is not None:
            # 确认后重跑：复用原记录，避免产生重复记录
            call = self.db.get_tool_call(existing_call_id)
            assert call is not None
        else:
            call = self.db.add_tool_call(self.task_id, seq, name, args)
        t0 = time.perf_counter()
        try:
            tool_result = self.registry.execute(name, args, ctx)
            status = "success"
        except NeedsConfirmation as e:
            self.db.update_tool_call(call.id, status="waiting_confirm")
            self._pending = (name, args, seq, call.id, tool_call_id)
            self._emit(
                "tool_end",
                name=name,
                status="waiting_confirm",
                reason=e.reason,
                seq=seq,
            )
            raise AgentPaused(call.id, e.reason) from e
        except ValidationError as e:
            tool_result = None
            feedback = arg_error(e)
            status = "failed"
        except Exception as e:  # noqa: BLE001 - 工具实现错误回给模型，不中断任务
            tool_result = None
            feedback = f"工具执行出错: {e}"
            status = "failed"
        duration = time.perf_counter() - t0

        if tool_result is not None:
            feedback = self._tool_feedback(tool_result)
            self._emit(
                "tool_end",
                name=name,
                status=status,
                summary=tool_result.summary,
                files=tool_result.files,
                duration=round(duration, 3),
                seq=seq,
            )
        else:
            self._emit(
                "tool_end",
                name=name,
                status=status,
                summary=feedback,
                duration=round(duration, 3),
                seq=seq,
            )
        self.db.update_tool_call(
            call.id,
            result=tool_result.data if tool_result is not None else None,
            status=status,
            duration_s=duration,
        )
        self._tool_steps += 1
        self._recent_calls.append((name, json.dumps(args, sort_keys=True)))
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": feedback[: self.settings.agent.max_tool_output_chars],
            }
        )

    def _append_tool_feedback(self, tool_call_id: str, content: str) -> None:
        self._messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    def _update_plan_from_tool(self, steps: list[str]) -> None:
        """工具 update_plan 的回调：执行中动态重排剩余计划（同步 DB 与 UI）。"""
        cleaned = [s.strip() for s in steps if s and s.strip()]
        self._plan = [PlanStep(goal=g) for g in cleaned[:20]]
        plan_json = json.dumps(
            [s.model_dump() for s in self._plan], ensure_ascii=False
        )
        self.db.update_task(self.task_id, plan_json=plan_json)
        self._emit("plan", plan=[s.model_dump() for s in self._plan])

    # ---------- 反思（自检） ----------

    def _maybe_reflect(self) -> bool:
        """模型给出最终产出后做一轮自检。

        返回 True=直接收尾（评审通过 / 无法评审 / 已达反思上限）；
        返回 False=评审发现问题，已把返工意见注入对话，应继续循环。
        """
        max_rounds = self.settings.agent.max_reflections
        if max_rounds <= 0 or self._reflection_rounds >= max_rounds:
            return True
        self._reflection_rounds += 1
        try:
            judge = self.llm.chat(
                messages=self._trimmed() + [{"role": "user", "content": REFLECT_PROMPT}],
                tools=[],
            )
        except Exception:  # noqa: BLE001 - 评审故障不影响任务本身：保守收尾
            return True
        verdict, issues = self._parse_verdict(judge.content or "")
        if verdict != "rework":
            return True
        if not issues:
            return True
        self._emit("message", content=f"[反思] 自检发现问题，要求返工：{issues}")
        self._messages.append(
            {
                "role": "user",
                "content": (
                    "你是执行者。评审者对你刚才的产出提出如下问题：\n"
                    f"问题：{issues}\n"
                    "请针对问题修正（可继续调用工具核实/补做，不要只复述结论），"
                    "修正完成后给出最终总结。"
                ),
            }
        )
        return False

    @staticmethod
    def _parse_verdict(text: str) -> tuple[str, str]:
        """从评审输出中解析 (verdict, issues)；容错：剥代码块、正则兜底、失败按 pass。"""
        cleaned = text.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
        try:
            obj = json.loads(cleaned)
            return str(obj.get("verdict", "pass")), str(obj.get("issues", ""))
        except (json.JSONDecodeError, AttributeError):
            m = re.search(r'"verdict"\s*:\s*"(pass|rework)"', cleaned)
            if m:
                issues_m = re.search(r'"issues"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)
                issues = issues_m.group(1) if issues_m else ""
                return m.group(1), issues
            return "pass", ""

    def _finish(self, status: str) -> TaskRecord:
        summary = (
            self.final_summary
            or f"任务{'完成' if status == 'done' else '结束'}，共执行 {self._tool_steps} 步工具调用"
        )
        cost = round(self.llm.stats.cost_yuan, 4)
        self.db.add_message(self.session_id, "assistant", summary[:2000])
        self.db.update_task(
            self.task_id,
            status=status,
            summary=summary[:2000],
            steps=self._tool_steps,
            cost_yuan=cost,
        )
        self._emit(
            status,
            summary=summary[:2000],
            steps=self._tool_steps,
            cost=cost,
            files=self._collected_files(),
        )
        task = self.db.get_task(self.task_id)
        assert task is not None
        return task

    def _collected_files(self) -> list[str]:
        """汇总任务所有工具调用涉及的文件（供验收清单）。"""
        files: list[str] = []
        for call in self.db.list_tool_calls(self.task_id):
            if call.status == "success" and call.result_json:
                try:
                    data = json.loads(call.result_json)
                    if isinstance(data, dict) and data.get("path"):
                        files.append(str(data["path"]))
                except json.JSONDecodeError:
                    continue
        return files

    # ---------- 护栏 ----------

    def _check_guards(self) -> str | None:
        """返回终止原因；None 表示可继续。"""
        if self.cancel_event.is_set():
            return "用户取消了任务"
        if self._tool_steps >= self.settings.agent.max_steps:
            return f"达到最大步数上限（{self.settings.agent.max_steps} 步）"
        if self.llm.stats.cost_yuan >= self.settings.agent.max_cost_yuan:
            return f"达到成本上限（{self.settings.agent.max_cost_yuan} 元）"
        if self._is_repeating():
            n = self.settings.agent.max_repeated_actions
            return f"检测到重复动作（连续 {n} 次相同调用）"
        return None

    def _is_repeating(self) -> bool:
        n = self.settings.agent.max_repeated_actions
        if len(self._recent_calls) < n:
            return False
        return len(set(self._recent_calls[-n:])) == 1

    # ---------- 工具辅助 ----------

    def _tool_feedback(self, result: ToolResult) -> str:
        """工具结果回填给模型：summary + data 序列化（截断）。"""
        max_chars = self.settings.agent.max_tool_output_chars
        parts = [result.summary]
        if result.data is not None:
            try:
                parts.append(json.dumps(result.data, ensure_ascii=False, default=str))
            except (TypeError, ValueError):
                parts.append(str(result.data))
        return "\n".join(parts)[: max_chars + 500]

    @staticmethod
    def _tool_call_dicts(calls: list[dict[str, str]]) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"]},
            }
            for c in calls
        ]

    def _trimmed(self) -> list[dict[str, Any]]:
        """裁剪历史：保留 system + 用户请求，加最近 N 条。"""
        if len(self._messages) <= MAX_HISTORY_MESSAGES:
            return self._messages
        head = self._messages[:2]
        tail = self._messages[-(MAX_HISTORY_MESSAGES - 2) :]
        return head + tail
