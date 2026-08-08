"""工具注册表测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from agentdesk.config import load_settings
from agentdesk.tools.registry import (
    NeedsConfirmation,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
)


class GreetParams(BaseModel):
    name: str
    count: int = 1


class DangerParams(BaseModel):
    path: str


def _greet(args: dict, ctx: ToolContext) -> ToolResult:
    return ToolResult(summary=f"你好 {args['name']} x{args['count']}", data={"ok": True})


def _danger(args: dict, ctx: ToolContext) -> ToolResult:
    if not ctx.confirmed:
        raise NeedsConfirmation(f"将删除 {args['path']}", {"path": args["path"]})
    return ToolResult(summary=f"已删除 {args['path']}", files=[args["path"]])


def _make_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(name="greet", description="打招呼", parameters=GreetParams, func=_greet),
            Tool(
                name="delete_file",
                description="删除文件（危险）",
                parameters=DangerParams,
                func=_danger,
                risky=True,
            ),
        ]
    )


def test_register_duplicate_raises() -> None:
    reg = ToolRegistry()
    reg.register(Tool(name="greet", description="d", parameters=GreetParams, func=_greet))
    with pytest.raises(ValueError, match="已注册"):
        reg.register(Tool(name="greet", description="d", parameters=GreetParams, func=_greet))


def test_get_unknown_raises() -> None:
    reg = _make_registry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_json_schema_generated_from_pydantic() -> None:
    reg = _make_registry()
    schema = reg.get("greet").json_schema()
    assert schema["properties"]["name"]["type"] == "string"
    assert "count" in schema["properties"]
    assert schema["required"] == ["name"]


def test_openai_schema_format() -> None:
    reg = _make_registry()
    schemas = reg.openai_schema()
    assert len(schemas) == 2
    first = schemas[0]
    assert first["type"] == "function"
    assert first["function"]["name"] == "greet"
    assert "parameters" in first["function"]


def test_execute_validates_args() -> None:
    reg = _make_registry()
    ctx = ToolContext(workspace_root=Path("."), settings=load_settings())
    with pytest.raises(ValidationError):
        reg.execute("greet", {}, ctx)  # 缺 name


def test_execute_success() -> None:
    reg = _make_registry()
    ctx = ToolContext(workspace_root=Path("."), settings=load_settings())
    result = reg.execute("greet", {"name": "小明"}, ctx)
    assert result.summary == "你好 小明 x1"


def test_risky_tool_requires_confirmation() -> None:
    reg = _make_registry()
    ctx = ToolContext(workspace_root=Path("."), settings=load_settings())
    with pytest.raises(NeedsConfirmation) as exc:
        reg.execute("delete_file", {"path": "a.txt"}, ctx)
    assert "删除" in exc.value.reason

    # 确认后重跑成功
    ctx.confirmed = True
    result = reg.execute("delete_file", {"path": "a.txt"}, ctx)
    assert result.files == ["a.txt"]
