"""工具层测试：路径安全、文件操作、表格处理、代码执行（全用临时工作目录）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentdesk.config import load_settings
from agentdesk.tools import build_default_tools
from agentdesk.tools.pathutils import resolve_in_workspace
from agentdesk.tools.registry import (
    NeedsConfirmation,
    ToolContext,
    ToolRegistry,
)

CSV_CONTENT = "name,score\n张三,88\n李四,92\n王五,75\n"


@pytest.fixture()
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, settings=load_settings(), confirmed=False)


@pytest.fixture()
def reg() -> ToolRegistry:
    return ToolRegistry(build_default_tools())


def test_registry_contains_all_tools(reg: ToolRegistry) -> None:
    expected = {
        "list_files",
        "read_file",
        "write_file",
        "move_file",
        "delete_file",
        "make_dir",
        "organize_by_type",
        "count_files",
        "read_table",
        "merge_tables",
        "describe_table",
        "run_python",
        "web_search",
        "fetch_page",
        "research_report",
    }
    assert set(reg.names()) == expected


# ---------- 路径安全 ----------

def test_path_traversal_blocked(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="超出工作目录"):
        resolve_in_workspace(tmp_path, "../outside.txt")
    with pytest.raises(ValueError, match="超出工作目录"):
        resolve_in_workspace(tmp_path, str(tmp_path.parent / "evil.txt"))


def test_path_inside_ok(tmp_path: Path) -> None:
    p = resolve_in_workspace(tmp_path, "sub/file.txt")
    assert p == (tmp_path / "sub" / "file.txt").resolve()


# ---------- 文件操作 ----------

def test_write_read_roundtrip(reg: ToolRegistry, ctx: ToolContext) -> None:
    r = reg.execute("write_file", {"path": "a.txt", "content": "hello"}, ctx)
    assert "已写入" in r.summary
    r2 = reg.execute("read_file", {"path": "a.txt"}, ctx)
    assert r2.data["content"] == "hello"  # type: ignore[index]


def test_write_overwrite_requires_confirmation(
    reg: ToolRegistry, ctx: ToolContext
) -> None:
    reg.execute("write_file", {"path": "a.txt", "content": "v1"}, ctx)
    with pytest.raises(NeedsConfirmation):
        reg.execute("write_file", {"path": "a.txt", "content": "v2"}, ctx)
    ctx.confirmed = True
    reg.execute("write_file", {"path": "a.txt", "content": "v2"}, ctx)
    assert (ctx.workspace_root / "a.txt").read_text(encoding="utf-8") == "v2"


def test_delete_requires_confirmation(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "del.txt").write_text("x", encoding="utf-8")
    with pytest.raises(NeedsConfirmation):
        reg.execute("delete_file", {"path": "del.txt"}, ctx)
    ctx.confirmed = True
    reg.execute("delete_file", {"path": "del.txt"}, ctx)
    assert not (ctx.workspace_root / "del.txt").exists()


def test_move_and_list(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "a.txt").write_text("x", encoding="utf-8")
    reg.execute("move_file", {"src": "a.txt", "dst": "sub/b.txt"}, ctx)
    assert (ctx.workspace_root / "sub" / "b.txt").exists()
    r = reg.execute("list_files", {"path": "."}, ctx)
    names = {e["name"] for e in r.data["entries"]}  # type: ignore[index]
    assert names == {"sub"}


def test_make_dir_creates_multiple(reg: ToolRegistry, ctx: ToolContext) -> None:
    r = reg.execute("make_dir", {"paths": ["a/b", "c/d/e"]}, ctx)
    assert (ctx.workspace_root / "a" / "b").is_dir()
    assert (ctx.workspace_root / "c" / "d" / "e").is_dir()
    assert "已创建 2 个目录" in r.summary


def test_organize_by_type(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "a.csv").write_text("x", encoding="utf-8")
    (ctx.workspace_root / "b.txt").write_text("y", encoding="utf-8")
    (ctx.workspace_root / "c.md").write_text("z", encoding="utf-8")
    r = reg.execute("organize_by_type", {"directory": "."}, ctx)
    assert r.data["moved"] == 3  # type: ignore[index]
    assert (ctx.workspace_root / "csv" / "a.csv").exists()
    assert (ctx.workspace_root / "text" / "b.txt").exists()
    assert (ctx.workspace_root / "docs" / "c.md").exists()


def test_count_files(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "a.md").write_text("x", encoding="utf-8")
    (ctx.workspace_root / "b.py").write_text("x", encoding="utf-8")
    sub = ctx.workspace_root / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("x", encoding="utf-8")
    r = reg.execute("count_files", {"directory": ""}, ctx)
    assert r.data["total"] == 3  # type: ignore[index]
    assert r.data["counts"] == {".md": 2, ".py": 1}  # type: ignore[index]
    assert "共 3 个文件" in r.summary
    # 子目录定向统计
    r2 = reg.execute("count_files", {"directory": "sub"}, ctx)
    assert r2.data["total"] == 1  # type: ignore[index]


def test_organize_by_type_idempotent(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "a.csv").write_text("x", encoding="utf-8")
    reg.execute("organize_by_type", {"directory": "."}, ctx)
    r2 = reg.execute("organize_by_type", {"directory": "."}, ctx)
    assert r2.data["moved"] == 0  # type: ignore[index]
    assert (ctx.workspace_root / "csv" / "a.csv").exists()


def test_organize_by_type_custom_mapping(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "cfg.ini").write_text("x", encoding="utf-8")
    reg.execute("organize_by_type", {"directory": ".", "mapping": {"ini": "config"}}, ctx)
    assert (ctx.workspace_root / "config" / "cfg.ini").exists()


def test_organize_by_type_skips_same_name(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "a.csv").write_text("x", encoding="utf-8")
    (ctx.workspace_root / "csv").mkdir()
    (ctx.workspace_root / "csv" / "a.csv").write_text("existing", encoding="utf-8")
    r = reg.execute("organize_by_type", {"directory": "."}, ctx)
    assert r.data["skipped"] == 1  # type: ignore[index]
    assert (ctx.workspace_root / "csv" / "a.csv").read_text(encoding="utf-8") == "existing"


# ---------- 表格处理 ----------

def test_read_table(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "scores.csv").write_text(CSV_CONTENT, encoding="utf-8")
    r = reg.execute("read_table", {"path": "scores.csv"}, ctx)
    data = r.data
    assert data["columns"] == ["name", "score"]  # type: ignore[index]
    assert data["rows"] == 3  # type: ignore[index]
    assert data["preview"][0]["name"] == "张三"  # type: ignore[index]


def test_merge_tables(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "a.csv").write_text(CSV_CONTENT, encoding="utf-8")
    (ctx.workspace_root / "b.csv").write_text("name,score\n赵六,60\n", encoding="utf-8")
    r = reg.execute("merge_tables", {"paths": ["a.csv", "b.csv"], "output": "all.csv"}, ctx)
    assert (ctx.workspace_root / "all.csv").exists()
    assert r.data["output_rows"] == 4  # type: ignore[index]


def test_describe_table(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "scores.csv").write_text(CSV_CONTENT, encoding="utf-8")
    r = reg.execute("describe_table", {"path": "scores.csv"}, ctx)
    cols = r.data["columns"]  # type: ignore[index]
    assert cols["score"]["type"] == "numeric"
    assert cols["score"]["mean"] == pytest.approx(85.0)


# ---------- 代码执行 ----------

def test_run_python_requires_confirmation(reg: ToolRegistry, ctx: ToolContext) -> None:
    with pytest.raises(NeedsConfirmation):
        reg.execute("run_python", {"code": "print(1)"}, ctx)


def test_run_python_success(reg: ToolRegistry, ctx: ToolContext) -> None:
    ctx.confirmed = True
    r = reg.execute("run_python", {"code": "print('ok')"}, ctx)
    assert r.data["returncode"] == 0  # type: ignore[index]
    assert "ok" in r.data["stdout"]  # type: ignore[index]


def test_run_python_works_in_workspace(reg: ToolRegistry, ctx: ToolContext) -> None:
    (ctx.workspace_root / "in.txt").write_text("data", encoding="utf-8")
    ctx.confirmed = True
    code = (
        "from pathlib import Path\n"
        "p = Path('out.txt')\n"
        "p.write_text(Path('in.txt').read_text() + '!', encoding='utf-8')\n"
        "print('done')"
    )
    r = reg.execute("run_python", {"code": code}, ctx)
    assert r.data["returncode"] == 0  # type: ignore[index]
    assert (ctx.workspace_root / "out.txt").read_text(encoding="utf-8") == "data!"


def test_run_python_timeout(reg: ToolRegistry, ctx: ToolContext) -> None:
    ctx.confirmed = True
    r = reg.execute("run_python", {"code": "import time; time.sleep(30)", "timeout": 1}, ctx)
    assert "超时" in r.summary
