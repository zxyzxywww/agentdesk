"""备份与撤销回滚测试：覆盖/删除/移动前自动备份，restore 一键还原。"""

from __future__ import annotations

from pathlib import Path

from agentdesk.config import load_settings
from agentdesk.storage.backup import BackupManager
from agentdesk.storage.db import DB
from agentdesk.tools import build_default_tools
from agentdesk.tools.registry import ToolContext, ToolRegistry


def _env(tmp_path: Path) -> tuple[ToolRegistry, ToolContext, DB, BackupManager]:
    settings = load_settings()
    settings.workspace.root = str(tmp_path)
    settings.storage.backups_dir = str(tmp_path / "backups")
    db = DB(db_path=tmp_path / "test.db", settings=settings)
    session = db.create_session()
    task = db.create_task(session.id, "任务")
    ctx = ToolContext(
        workspace_root=tmp_path,
        settings=settings,
        confirmed=False,
        db=db,
        task_id=task.id,
    )
    mgr = BackupManager(db, settings.backups_dir_abs, tmp_path)
    return ToolRegistry(build_default_tools()), ctx, db, mgr


def test_overwrite_then_restore(tmp_path: Path) -> None:
    reg, ctx, db, mgr = _env(tmp_path)
    (tmp_path / "a.txt").write_text("v1", encoding="utf-8")
    # 第一次覆盖需确认
    ctx.confirmed = False
    from agentdesk.tools.registry import NeedsConfirmation

    try:
        reg.execute("write_file", {"path": "a.txt", "content": "v2"}, ctx)
        raise AssertionError("应抛 NeedsConfirmation")
    except NeedsConfirmation:
        pass
    ctx.confirmed = True
    reg.execute("write_file", {"path": "a.txt", "content": "v2"}, ctx)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "v2"
    backups = db.list_backups()
    assert len(backups) == 1
    assert backups[0].op == "overwrite"
    assert backups[0].src_rel == "a.txt"
    assert mgr.restore(backups[0].id)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "v1"


def test_delete_then_restore_file(tmp_path: Path) -> None:
    reg, ctx, db, mgr = _env(tmp_path)
    (tmp_path / "del.txt").write_text("keep me", encoding="utf-8")
    ctx.confirmed = True
    reg.execute("delete_file", {"path": "del.txt"}, ctx)
    assert not (tmp_path / "del.txt").exists()
    backups = db.list_backups()
    assert len(backups) == 1 and backups[0].op == "delete"
    assert mgr.restore(backups[0].id)
    assert (tmp_path / "del.txt").read_text(encoding="utf-8") == "keep me"


def test_delete_then_restore_directory(tmp_path: Path) -> None:
    reg, ctx, db, mgr = _env(tmp_path)
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "inner.txt").write_text("data", encoding="utf-8")
    ctx.confirmed = True
    reg.execute("delete_file", {"path": "dir", "recursive": True}, ctx)
    assert not (tmp_path / "dir").exists()
    backups = db.list_backups()
    assert len(backups) == 1
    assert mgr.restore(backups[0].id)
    assert (tmp_path / "dir" / "inner.txt").read_text(encoding="utf-8") == "data"


def test_move_overwrite_backup_dst(tmp_path: Path) -> None:
    reg, ctx, db, mgr = _env(tmp_path)
    (tmp_path / "src.txt").write_text("new content", encoding="utf-8")
    (tmp_path / "dst.txt").write_text("old dst", encoding="utf-8")
    ctx.confirmed = True
    reg.execute("move_file", {"src": "src.txt", "dst": "dst.txt"}, ctx)
    assert (tmp_path / "dst.txt").read_text(encoding="utf-8") == "new content"
    backups = db.list_backups()
    assert len(backups) == 1 and backups[0].src_rel == "dst.txt"
    assert mgr.restore(backups[0].id)
    assert (tmp_path / "dst.txt").read_text(encoding="utf-8") == "old dst"


def test_backup_dir_outside_workspace() -> None:
    """实际部署配置下，备份区（data/backups）在工作目录（data/workspace）之外，
    工具不可见（防误删），且互不包含。"""
    settings = load_settings()
    ws = settings.workspace_root.resolve()
    bk = settings.backups_dir_abs.resolve()
    assert ws != bk
    assert ws not in bk.parents
    assert bk not in ws.parents


def test_restore_missing_backup_returns_false(tmp_path: Path) -> None:
    _, _, db, mgr = _env(tmp_path)
    assert not mgr.restore(99999)
