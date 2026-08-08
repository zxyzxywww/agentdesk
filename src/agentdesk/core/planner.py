"""任务规划：把用户请求解析为步骤计划（供前端展示与执行参考）。

计划是「建议」而非「强制」：执行循环按 ReAct 动态推进，
计划用于给用户可见的任务结构，并帮助 LLM 保持任务主线。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from agentdesk.config import Settings
from agentdesk.llm.client import ChatResult, LLMClient

MAX_PLAN_STEPS = 6

PLAN_PROMPT = """你是 AgentDesk 的任务规划器。把用户的请求拆解为清晰的执行步骤计划。

要求：
- 1~{max_steps} 步，每步一句话目标（中文）
- tool 字段从可用工具中选择最可能用到的（不确定写 null）
- 只输出 JSON 数组，不要任何其他文字
- 格式: [{{"goal": "步骤目标", "tool": "工具名或null", "note": "补充说明"}}]

可用工具：
{tools}

用户请求：{request}
"""


class PlanStep(BaseModel):
    goal: str
    tool: str | None = None
    note: str = ""


def _extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（容忍 markdown 代码块包裹）。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return json.loads(text)


class Planner:
    """基于 LLM 的任务规划器，解析失败时回退为单步兜底计划。"""

    def __init__(self, llm: LLMClient, settings: Settings | None = None) -> None:
        self.llm = llm
        self.settings = settings

    def plan(self, user_request: str, tools_schema: list[dict]) -> list[PlanStep]:
        """生成步骤计划。"""
        tool_list = [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
            }
            for t in tools_schema
        ]
        prompt = PLAN_PROMPT.format(
            max_steps=MAX_PLAN_STEPS,
            tools=json.dumps(tool_list, ensure_ascii=False),
            request=user_request,
        )
        result: ChatResult = self.llm.chat(
            messages=[
                {"role": "system", "content": "你是任务规划器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ]
        )
        return self._parse(result.content or "", user_request, tool_list)

    def _parse(
        self, content: str, request: str, tool_list: list[dict]
    ) -> list[PlanStep]:
        tool_names = {t["name"] for t in tool_list}
        try:
            raw = _extract_json(content)
            if not isinstance(raw, list) or not raw:
                raise ValueError("空计划")
            steps = [PlanStep.model_validate(item) for item in raw[:MAX_PLAN_STEPS]]
            for step in steps:
                if step.tool not in tool_names:
                    step.tool = None
            return steps
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
            return [
                PlanStep(
                    goal=f"完成请求：{request[:100]}",
                    tool=None,
                    note="自动规划失败，将按 ReAct 动态推进",
                )
            ]
