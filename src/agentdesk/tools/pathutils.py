"""工作目录路径安全：所有文件操作被锁定在 workspace 内，防止路径穿越。"""

from __future__ import annotations

from pathlib import Path


def resolve_in_workspace(workspace_root: Path, path: str) -> Path:
    """把相对/绝对路径解析为 workspace 内的绝对路径；越界抛 ValueError。

    - 相对路径相对于 workspace_root 解析；
    - 绝对路径必须位于 workspace_root 之内；
    - 通过 resolve() 展开符号链接与 '..' 后再校验。
    """
    raw = Path(path)
    candidate = raw if raw.is_absolute() else (workspace_root / raw)
    candidate = candidate.resolve()
    root = workspace_root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"路径超出工作目录: {path!r}")
    return candidate


def rel_or_abs(path: Path, workspace_root: Path) -> str:
    """返回相对 workspace 的路径（用于展示/存储）；无法相对时返回绝对路径。"""
    try:
        return str(path.relative_to(workspace_root.resolve()))
    except ValueError:
        return str(path)
