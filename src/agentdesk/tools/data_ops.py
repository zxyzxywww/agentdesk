"""Excel/CSV 数据处理工具（基于 pandas）：表格预览、合并、描述统计。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from agentdesk.tools.pathutils import rel_or_abs, resolve_in_workspace
from agentdesk.tools.registry import NeedsConfirmation, Tool, ToolContext, ToolResult

_SUPPORTED = {".csv", ".xlsx", ".xls"}


def _read_df(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED:
        raise ValueError(f"不支持的文件类型: {suffix}（支持 csv/xlsx）")
    if suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _clean_value(v: object) -> object:
    """NaN → None，其余原样（供 JSON 序列化）。"""
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v


def _preview_records(df: pd.DataFrame, max_rows: int) -> list[dict]:
    """前 N 行转为可 JSON 序列化的记录（NaN → None）。"""
    head = df.head(max_rows).astype(object).where(pd.notna(df), None)
    return [
        {str(k): _clean_value(v) for k, v in row.items()}
        for row in head.to_dict(orient="records")
    ]


class ReadTableParams(BaseModel):
    path: str = Field(description="表格文件路径（相对工作目录），支持 csv/xlsx")
    max_rows: int = Field(default=50, ge=1, le=1000)


def _read_table(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    if not target.is_file():
        return ToolResult(summary=f"文件不存在: {args['path']}")
    try:
        df = _read_df(target)
    except Exception as e:  # noqa: BLE001 - 工具层兜底，把错误回给模型
        return ToolResult(summary=f"读取失败: {e}")
    cols = [str(c) for c in df.columns]
    truncated = df.shape[0] > args["max_rows"]
    rel = rel_or_abs(target, ctx.workspace_root)
    return ToolResult(
        summary=(
            f"表格 {rel}: {df.shape[0]} 行 x {df.shape[1]} 列，"
            f"列: {', '.join(cols[:10])}{'…' if len(cols) > 10 else ''}"
        ),
        data={
            "path": rel,
            "columns": cols,
            "rows": int(df.shape[0]),
            "preview": _preview_records(df, args["max_rows"]),
            "truncated": truncated,
        },
        files=[rel],
    )


class MergeTablesParams(BaseModel):
    paths: list[str] = Field(description="要合并的表格文件列表（csv/xlsx）", min_length=2)
    output: str = Field(description="输出文件路径（csv/xlsx）")


def _merge_tables(args: dict, ctx: ToolContext) -> ToolResult:
    frames: list[pd.DataFrame] = []
    names: list[str] = []
    for p in args["paths"]:
        target = resolve_in_workspace(ctx.workspace_root, p)
        if not target.is_file():
            return ToolResult(summary=f"文件不存在: {p}")
        try:
            frames.append(_read_df(target))
        except Exception as e:  # noqa: BLE001
            return ToolResult(summary=f"读取 {p} 失败: {e}")
        names.append(rel_or_abs(target, ctx.workspace_root))
    merged = pd.concat(frames, ignore_index=True)
    out = resolve_in_workspace(ctx.workspace_root, args["output"])
    if out.exists() and not ctx.confirmed:
        raise NeedsConfirmation(
            f"输出文件已存在，将覆盖: {args['output']}", {"path": args["output"]}
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        ctx.backup(out, op="overwrite")  # 覆盖输出前自动备份（可撤销）
    suffix = out.suffix.lower()
    if suffix == ".csv":
        merged.to_csv(out, index=False, encoding="utf-8-sig")
    elif suffix in (".xlsx", ".xls"):
        merged.to_excel(out, index=False)
    else:
        return ToolResult(summary=f"输出格式不支持: {suffix}（支持 csv/xlsx）")
    rel_out = rel_or_abs(out, ctx.workspace_root)
    return ToolResult(
        summary=f"已合并 {len(frames)} 个文件（共 {merged.shape[0]} 行）→ {rel_out}",
        data={"output": rel_out, "output_rows": int(merged.shape[0]), "sources": names},
        files=[rel_out],
    )


class DescribeTableParams(BaseModel):
    path: str = Field(description="表格文件路径（相对工作目录）")
    max_cols: int = Field(default=20, ge=1, le=200)


def _describe_table(args: dict, ctx: ToolContext) -> ToolResult:
    target = resolve_in_workspace(ctx.workspace_root, args["path"])
    if not target.is_file():
        return ToolResult(summary=f"文件不存在: {args['path']}")
    try:
        df = _read_df(target)
    except Exception as e:  # noqa: BLE001
        return ToolResult(summary=f"读取失败: {e}")
    info: dict[str, dict] = {}
    for col in df.columns[: args["max_cols"]]:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            info[str(col)] = {
                "type": "numeric",
                "mean": None if s.empty else float(s.mean()),
                "min": None if s.empty else float(s.min()),
                "max": None if s.empty else float(s.max()),
                "nunique": int(s.nunique()),
            }
        else:
            modes = s.dropna().mode()
            info[str(col)] = {
                "type": "object",
                "nunique": int(s.nunique()),
                "top": str(modes.iloc[0]) if len(modes) else None,
            }
    rel = rel_or_abs(target, ctx.workspace_root)
    return ToolResult(
        summary=f"表格 {rel}: {df.shape[0]} 行 x {df.shape[1]} 列，已描述 {len(info)} 列",
        data={"path": rel, "rows": int(df.shape[0]), "columns": info},
        files=[rel],
    )


def build_data_tools() -> list[Tool]:
    """表格数据处理工具集。"""
    return [
        Tool(
            name="read_table",
            description="读取表格（csv/xlsx）并预览前若干行与列信息",
            parameters=ReadTableParams,
            func=_read_table,
        ),
        Tool(
            name="merge_tables",
            description="按列对齐合并多个表格（csv/xlsx）为一个输出文件",
            parameters=MergeTablesParams,
            func=_merge_tables,
            risky=True,
        ),
        Tool(
            name="describe_table",
            description="统计表格各列的类型/均值/极值/唯一值数",
            parameters=DescribeTableParams,
            func=_describe_table,
        ),
    ]
