"""规划调整工具：执行中动态更新剩余计划（Plan-and-Execute 的动态调整）。

初始计划只是"建议"；当执行中发现需求变化、资料不足、原步骤已不适用时，
Agent 可调用 update_plan 重排剩余步骤，UI 同步展示新计划。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentdesk.tools.registry import Tool, ToolContext, ToolResult


class UpdatePlanParams(BaseModel):
    """更新剩余执行计划。"""

    steps: list[str] = Field(
        min_length=1,
        max_length=20,
        description="新的剩余步骤列表，每项一句目标（按执行顺序）；从当前未完成处开始",
    )


def _update_plan(args: dict, ctx: ToolContext) -> ToolResult:
    if ctx.update_plan is None:
        return ToolResult(summary="当前执行环境不支持动态更新计划")
    ctx.update_plan(args["steps"])
    return ToolResult(
        summary=f"已更新计划为 {len(args['steps'])} 步，继续按新计划执行",
        data={"steps": args["steps"]},
    )


def build_plan_tools() -> list[Tool]:
    """规划调整工具集。"""
    return [
        Tool(
            name="update_plan",
            description=(
                "执行中动态更新剩余计划（原计划只是建议）。当需求变化、某步已无必要、"
                "或需要拆分/合并步骤时调用；传入从当前未完成处开始的新步骤列表。"
            ),
            parameters=UpdatePlanParams,
            func=_update_plan,
        ),
    ]
