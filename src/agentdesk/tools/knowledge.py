"""本地知识检索工具：在工作目录内按关键词检索文本文件（轻量 RAG 检索雏形）。

只读安全；关键词大小写不敏感子串匹配，返回命中文件与上下文片段，
供 Agent 报告引用本地文档/笔记内容，避免编造。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentdesk.tools.pathutils import resolve_in_workspace
from agentdesk.tools.registry import Tool, ToolContext, ToolResult

_TEXT_EXTS = {".md", ".txt", ".log", ".csv", ".json", ".py", ".html", ".ini"}
_MAX_PER_FILE = 3  # 每个文件最多保留的命中片段数
_MAX_SNIPPET = 200  # 单个片段最大字符数


class KnowledgeSearchParams(BaseModel):
    """本地知识检索：按关键词在工作目录内搜索文本文件内容（只读）。"""

    keyword: str = Field(min_length=1, description="要检索的关键词（不区分大小写）")
    directory: str = Field(
        default=".", description="检索范围（相对工作目录），默认整个工作目录"
    )


def _knowledge_search(args: dict, ctx: ToolContext) -> ToolResult:
    keyword = args["keyword"].lower()
    base = resolve_in_workspace(ctx.workspace_root, args["directory"])
    if not base.is_dir():
        return ToolResult(summary=f"目录不存在: {args['directory']}")
    hits: list[dict] = []
    total_matches = 0
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _TEXT_EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_hits: list[dict] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if keyword in line.lower():
                total_matches += 1
                snippet = line.strip()
                if len(snippet) > _MAX_SNIPPET:
                    snippet = snippet[: _MAX_SNIPPET] + "…"
                file_hits.append({"line": line_no, "snippet": snippet})
                if len(file_hits) >= _MAX_PER_FILE:
                    break
        if file_hits:
            hits.append(
                {"file": str(p.relative_to(ctx.workspace_root)), "hits": file_hits}
            )
    if not hits:
        return ToolResult(
            summary=f"未找到包含「{args['keyword']}」的内容（范围: {args['directory']}）",
            data={"keyword": args["keyword"], "total_matches": 0, "hits": []},
        )
    # 控制落库与回填体量：只保留前 8 个文件的命中片段
    shown = hits[:8]
    summary = (
        f"找到 {total_matches} 处「{args['keyword']}」匹配（{len(hits)} 个文件，"
        f"已列前 {len(shown)} 个）"
    )
    return ToolResult(
        summary=summary,
        data={
            "keyword": args["keyword"],
            "total_matches": total_matches,
            "files": len(hits),
            "hits": shown,
        },
    )


def build_knowledge_tools() -> list[Tool]:
    """本地知识检索工具集。"""
    return [
        Tool(
            name="knowledge_search",
            description=(
                "在本地工作目录的文本文件(md/txt/csv/log/json 等)中按关键词检索内容，"
                "返回命中文件与上下文片段。适合引用本地笔记/文档/既有产出，"
                "避免凭记忆编造。只读安全。"
            ),
            parameters=KnowledgeSearchParams,
            func=_knowledge_search,
        ),
    ]
