"""工具注册表：工具声明、参数校验（Pydantic 自动生成 JSON Schema）、统一执行入口。

设计：
- 每个工具用 Pydantic 模型声明参数 → 自动生成 JSON Schema（供 LLM 生成参数）并校验。
- 危险工具（risky=True）在执行时若需用户确认，抛 NeedsConfirmation；
  引擎挂起任务，用户确认后以 ctx.confirmed=True 重新执行。
- ToolResult 统一返回：summary（回填给模型）+ data（结构化，供前端预览）+ files（产出清单）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from agentdesk.config import Settings


class ToolContext:
    """工具执行上下文：工作目录、确认状态、运行配置、备份能力。"""

    def __init__(
        self,
        workspace_root: Path,
        settings: Settings,
        confirmed: bool = False,
        db: Any = None,
        task_id: str | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.settings = settings
        self.confirmed = confirmed
        self.db = db
        self.task_id = task_id
        self._backup_mgr: Any = None

    def backup(self, path: Path, op: str = "overwrite") -> int | None:
        """把将被覆盖/删除的内容备份；返回备份记录 id（无 DB 时返回 None）。"""
        if self.db is None or self.task_id is None:
            return None
        if self._backup_mgr is None:
            from agentdesk.storage.backup import BackupManager

            self._backup_mgr = BackupManager(
                self.db, self.settings.backups_dir_abs, self.workspace_root
            )
        return self._backup_mgr.backup(self.task_id, path, op)


@dataclass
class ToolResult:
    """工具执行结果。summary 会回填给模型；data/files 供前端展示与任务验收。"""

    summary: str
    data: Any = None
    files: list[str] = field(default_factory=list)
    truncated: bool = False


class NeedsConfirmation(Exception):
    """危险操作需用户确认：引擎捕获后挂起任务，等确认后重跑。"""

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class ToolFunc(Protocol):
    def __call__(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


@dataclass
class Tool:
    """一个工具的声明：名称、描述、参数模型、执行函数、是否危险。"""

    name: str
    description: str
    parameters: type[BaseModel]
    func: ToolFunc
    risky: bool = False

    def json_schema(self) -> dict[str, Any]:
        return self.parameters.model_json_schema()


class ToolRegistry:
    """工具集合：注册、查询、生成 OpenAI 工具 Schema、校验并分发执行。"""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具 {tool.name!r} 已注册")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"未知工具: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def openai_schema(self) -> list[dict[str, Any]]:
        """转成 OpenAI 函数调用格式，供 LLM 使用。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """校验参数并执行工具。参数非法抛 ValidationError；需确认抛 NeedsConfirmation。"""
        tool = self.get(name)
        params = tool.parameters.model_validate(args)
        return tool.func(params.model_dump(), ctx)


def arg_error(e: ValidationError) -> str:
    """把 Pydantic 校验错误转成给模型看的简短中文提示。"""
    parts = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
    return "参数校验失败: " + "; ".join(parts[:5])
