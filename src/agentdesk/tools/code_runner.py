"""Python 代码沙箱执行工具。

轻量沙箱边界（在 README 中如实披露）：
- 工作目录锁定（cwd=workspace），但进程本身不隔离系统资源/网络；
- 强制超时 + 输出截断，防失控；
- 执行前必须用户确认。
"""

from __future__ import annotations

import os
import subprocess
import sys

from pydantic import BaseModel, Field

from agentdesk.tools.registry import NeedsConfirmation, Tool, ToolContext, ToolResult


class RunPythonParams(BaseModel):
    code: str = Field(description="要执行的 Python 代码")
    timeout: int = Field(default=60, ge=1, le=300, description="超时秒数")


def _run_python(args: dict, ctx: ToolContext) -> ToolResult:
    if not ctx.confirmed:
        raise NeedsConfirmation(
            "将执行一段 Python 代码（在数据目录内运行，可读写该目录文件）",
            {"code_preview": args["code"][:200]},
        )
    max_out = ctx.settings.tools.code_runner.max_output_chars
    timeout = args["timeout"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", args["code"]],
            cwd=ctx.workspace_root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            summary=f"执行超时（>{timeout}s），已终止",
            data={"returncode": None, "stdout": "", "stderr": "TimeoutExpired"},
        )
    except OSError as e:
        return ToolResult(summary=f"无法启动解释器: {e}", data={"returncode": None})
    stdout = proc.stdout[-max_out:]
    stderr = proc.stderr[-max_out:]
    truncated = len(proc.stdout) > max_out or len(proc.stderr) > max_out
    ok = proc.returncode == 0
    tail = (stderr or stdout).strip().splitlines()
    preview = " | ".join(tail[-5:])[:400]
    return ToolResult(
        summary=(
            f"代码执行{'成功' if ok else f'失败(退出码 {proc.returncode})'}"
            + (f"：{preview}" if preview else "")
        ),
        data={
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
        },
    )


def build_code_tools() -> list[Tool]:
    """代码执行工具集。"""
    return [
        Tool(
            name="run_python",
            description=(
                "在数据目录内执行一段 Python 代码（可读写目录文件、做批量处理），"
                "返回标准输出/错误。执行前需用户确认。"
            ),
            parameters=RunPythonParams,
            func=_run_python,
            risky=True,
        )
    ]
