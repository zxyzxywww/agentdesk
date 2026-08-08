"""Planner 测试（mock LLM，离线）。"""

from __future__ import annotations

import json

from agentdesk.config import load_settings
from agentdesk.core.planner import MAX_PLAN_STEPS, Planner, _extract_json
from agentdesk.llm.client import ChatResult

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "列出目录内容",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_tables",
            "description": "合并表格",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class FakeLLM:
    """返回预设 content 的假 LLM。"""

    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages: list, **kwargs: object) -> ChatResult:
        return ChatResult(
            content=self.content,
            tool_calls=[],
            prompt_tokens=10,
            completion_tokens=5,
            model="fake",
        )


def _planner(content: str) -> Planner:
    return Planner(FakeLLM(content), settings=load_settings())


def test_plan_parses_valid_json() -> None:
    plan = [
        {"goal": "查看目录", "tool": "list_files", "note": "先看看有什么"},
        {"goal": "合并表格", "tool": "merge_tables", "note": ""},
    ]
    p = _planner(json.dumps(plan, ensure_ascii=False)).plan("合并 csv", TOOLS_SCHEMA)
    assert len(p) == 2
    assert p[0].goal == "查看目录"
    assert p[0].tool == "list_files"


def test_plan_tolerates_code_block() -> None:
    plan = [{"goal": "合并表格", "tool": "merge_tables"}]
    wrapped = f"```json\n{json.dumps(plan, ensure_ascii=False)}\n```"
    p = _planner(wrapped).plan("合并", TOOLS_SCHEMA)
    assert p[0].goal == "合并表格"


def test_unknown_tool_sanitized() -> None:
    plan = [{"goal": "搞事情", "tool": "not_a_tool"}, {"goal": "合并", "tool": "merge_tables"}]
    p = _planner(json.dumps(plan)).plan("任务", TOOLS_SCHEMA)
    assert p[0].tool is None
    assert p[1].tool == "merge_tables"


def test_plan_truncated_to_max() -> None:
    plan = [{"goal": f"步骤{i}"} for i in range(20)]
    p = _planner(json.dumps(plan)).plan("任务", TOOLS_SCHEMA)
    assert len(p) == MAX_PLAN_STEPS


def test_plan_fallback_on_garbage() -> None:
    p = _planner("这不是 JSON").plan("帮我整理文件", TOOLS_SCHEMA)
    assert len(p) == 1
    assert "整理文件" in p[0].goal
    assert p[0].tool is None


def test_plan_fallback_on_empty_list() -> None:
    p = _planner("[]").plan("任务", TOOLS_SCHEMA)
    assert len(p) == 1


def test_extract_json_plain() -> None:
    assert _extract_json('[{"goal": "a"}]') == [{"goal": "a"}]
