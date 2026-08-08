"""文件/目录操作工具：列表、读取、写入、移动、删除、建目录。

安全约定：
- 所有路径经 resolve_in_workspace 锁定在工作目录内；
- 覆盖已有文件、移动覆盖目标、删除一律需要用户确认（NeedsConfirmation）。
"""

from __future__ import annotations

import shutil
from datetime import datetime

from pydantic import BaseModel, Field

from agentdesk.tools.pathutils import rel_or_abs, resolve_in_workspace
from agentdesk.tools.registry import NeedsConfirmation, Tool, ToolContext, ToolResult

_MAX_ENTRIES = 200


class ListFilesParams(BaseModel):
    path: str = Field(default=".", description="目录路径（相对工作目录）")


def _list_files(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    if not target.exists():
        return ToolResult(summary=f"路径不存在: {args['path']}")
    if not target.is_dir():
        return ToolResult(summary=f"不是目录: {args['path']}")
    entries: list[dict] = []
    for child in sorted(target.iterdir()):
        if child.is_dir():
            entries.append({"name": child.name, "type": "dir", "size": 0, "modified": ""})
        else:
            try:
                st = child.stat()
                modified = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes")
            except OSError:
                st = None
                modified = ""
            entries.append(
                {
                    "name": child.name,
                    "type": "file",
                    "size": st.st_size if st else 0,
                    "modified": modified,
                }
            )
    truncated = len(entries) > _MAX_ENTRIES
    shown = entries[:_MAX_ENTRIES]
    summary = (
        f"目录 {args['path']} 共 {len(entries)} 项"
        + ("（仅显示前 200 项）" if truncated else "")
    )
    return ToolResult(
        summary=summary,
        data={"path": args["path"], "entries": shown, "truncated": truncated},
    )


class ReadFileParams(BaseModel):
    path: str = Field(description="文件路径（相对工作目录）")
    max_chars: int = Field(default=20000, ge=100, le=200000)


def _read_file(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    if not target.is_file():
        return ToolResult(summary=f"文件不存在或不是文件: {args['path']}")
    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > args["max_chars"]
    shown = content[: args["max_chars"]]
    if truncated:
        shown += f"\n...[已截断，全文 {len(content)} 字符]"
    return ToolResult(
        summary=f"已读取 {rel_or_abs(target, ctx.workspace_root)}（{len(content)} 字符）",
        data={"path": args["path"], "content": shown, "truncated": truncated},
    )


class WriteFileParams(BaseModel):
    path: str = Field(description="目标文件路径（相对工作目录）")
    content: str = Field(description="写入的文本内容")
    overwrite: bool = Field(default=False, description="是否允许覆盖已存在文件")


def _write_file(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    if target.exists() and not ctx.confirmed:
        raise NeedsConfirmation(
            f"将覆盖已存在的文件 {args['path']}", {"path": args["path"]}
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        ctx.backup(target, op="overwrite")  # 覆盖前自动备份（可撤销）
    target.write_text(args["content"], encoding="utf-8")
    rel = rel_or_abs(target, ctx.workspace_root)
    return ToolResult(
        summary=f"已写入 {rel}（{len(args['content'])} 字符）",
        data={"path": rel, "chars": len(args["content"])},
        files=[rel],
    )


class MoveFileParams(BaseModel):
    src: str = Field(description="源路径（相对工作目录）")
    dst: str = Field(description="目标路径（相对工作目录）")


def _move_file(args: dict, ctx: ToolContext) -> ToolResult:
    src = resolve_in_workspace(ctx.workspace_root, args["src"])
    dst = resolve_in_workspace(ctx.workspace_root, args["dst"])
    if not src.exists():
        return ToolResult(summary=f"源不存在: {args['src']}")
    if dst.exists() and not ctx.confirmed:
        raise NeedsConfirmation(
            f"目标已存在，移动将覆盖/合并: {args['dst']}", {"path": args["dst"]}
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        ctx.backup(dst, op="overwrite")  # 覆盖目标前自动备份（可撤销）
    shutil.move(str(src), str(dst))
    rel_dst = rel_or_abs(dst, ctx.workspace_root)
    return ToolResult(
        summary=f"已移动 {args['src']} → {rel_dst}",
        data={"src": args["src"], "dst": rel_dst},
        files=[rel_dst],
    )


class DeleteFileParams(BaseModel):
    path: str = Field(description="要删除的文件或目录（相对工作目录）")
    recursive: bool = Field(default=False, description="删除目录时需为 true")


def _delete_file(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    if not target.exists():
        return ToolResult(summary=f"路径不存在: {args['path']}")
    if not ctx.confirmed:
        raise NeedsConfirmation(
            f"将删除 {args['path']}"
            + ("（目录，含全部内容）" if target.is_dir() else ""),
            {"path": args["path"]},
        )
    ctx.backup(target, op="delete")  # 删除前自动备份（可撤销）
    if target.is_dir():
        if not args["recursive"]:
            return ToolResult(summary="目标为目录，请设置 recursive=true 后重试")
        shutil.rmtree(target)
    else:
        target.unlink()
    rel = rel_or_abs(target, ctx.workspace_root)
    return ToolResult(summary=f"已删除 {rel}", data={"path": rel}, files=[rel])


class MakeDirParams(BaseModel):
    path: str = Field(description="目录路径（相对工作目录）")


def _make_dir(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    target.mkdir(parents=True, exist_ok=True)
    rel = rel_or_abs(target, ctx.workspace_root)
    return ToolResult(summary=f"已创建目录 {rel}", data={"path": rel})


def build_file_tools() -> list[Tool]:
    """文件/目录工具集。"""
    return [
        Tool(
            name="list_files",
            description="列出目录内容（文件/子目录/大小）",
            parameters=ListFilesParams,
            func=_list_files,
        ),
        Tool(
            name="read_file",
            description="读取文本文件内容（可截断）",
            parameters=ReadFileParams,
            func=_read_file,
        ),
        Tool(
            name="write_file",
            description="写入/覆盖文本文件（覆盖已存在文件需用户确认）",
            parameters=WriteFileParams,
            func=_write_file,
            risky=True,
        ),
        Tool(
            name="move_file",
            description="移动/重命名文件或目录（覆盖目标需确认）",
            parameters=MoveFileParams,
            func=_move_file,
            risky=True,
        ),
        Tool(
            name="delete_file",
            description="删除文件或目录（危险，需用户确认；删目录需 recursive=true）",
            parameters=DeleteFileParams,
            func=_delete_file,
            risky=True,
        ),
        Tool(
            name="make_dir",
            description="创建目录（含父目录）",
            parameters=MakeDirParams,
            func=_make_dir,
        ),
    ]
