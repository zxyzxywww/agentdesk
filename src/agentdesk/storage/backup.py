"""文件备份与一键撤销回滚。

覆盖/删除发生前，把原始内容备份到项目 data/backups/（workspace 之外，
对工具不可见），并记录到 DB；restore() 把备份内容恢复到原路径。
"""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path

from agentdesk.storage.db import DB


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


class BackupManager:
    """备份与恢复。db 可为 None（纯备份不记录，用于无 DB 场景）。"""

    def __init__(self, db: DB | None, backups_dir: Path, workspace_root: Path) -> None:
        self.db = db
        self.backups_dir = backups_dir
        self.workspace_root = workspace_root
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def backup(self, task_id: str | None, path: Path, op: str = "overwrite") -> int | None:
        """备份 path（文件或目录），返回备份记录 id；path 不存在时返回 None。"""
        path = path.resolve()
        if not path.exists():
            return None
        try:
            rel = path.relative_to(self.workspace_root.resolve())
        except ValueError:
            rel = path
        dest_dir = self.backups_dir / f"{_stamp()}_{uuid.uuid4().hex[:6]}"
        dest = dest_dir / path.name
        if path.is_dir():
            shutil.copytree(path, dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        if self.db is None:
            return None
        return self.db.add_backup(
            task_id=task_id or "",
            op=op,
            src_rel=str(rel),
            backup_path=str(dest),
        )

    def restore(self, backup_id: int) -> bool:
        """把备份恢复到原路径。成功返回 True。"""
        if self.db is None:
            return False
        rec = self.db.get_backup(backup_id)
        if rec is None:
            return False
        backup_path = Path(rec.backup_path)
        if not backup_path.exists():
            return False
        target = self.workspace_root / rec.src_rel
        if backup_path.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(backup_path, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, target)
        self.db.mark_restored(backup_id)
        return True
