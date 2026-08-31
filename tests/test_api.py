"""Web 后端 API 测试：会话/任务/确认/取消/上传/备份/导出/WS 心跳（离线）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentdesk.config import load_settings
from agentdesk.llm.client import ChatResult, UsageStats
from agentdesk.storage.db import DB
from agentdesk.ui.main import AppState, create_app

PLAN = json.dumps([{"goal": "查看目录", "tool": "list_files"}], ensure_ascii=False)


class FakeLLM:
    """按脚本返回响应，带 stats（供 executor 护栏使用）。"""

    def __init__(self, responses: list[ChatResult], delay: float = 0.0) -> None:
        self.responses = list(responses)
        self.stats = UsageStats()
        self.delay = delay

    def chat(self, messages: list, **kwargs: object) -> ChatResult:
        self.stats.calls += 1
        self.stats.cost_yuan += 0.001
        if self.delay:
            time.sleep(self.delay)
        if not self.responses:
            return ChatResult(
                content="完成", tool_calls=[], prompt_tokens=0, completion_tokens=0, model="fake"
            )
        return self.responses.pop(0)


def _plan() -> ChatResult:
    return ChatResult(
        content=PLAN, tool_calls=[], prompt_tokens=0, completion_tokens=0, model="fake"
    )


def _tool(name: str, arguments: str = "{}") -> ChatResult:
    return ChatResult(
        content=None,
        tool_calls=[{"id": "c1", "name": name, "arguments": arguments}],
        prompt_tokens=0,
        completion_tokens=0,
        model="fake",
    )


def _text(content: str) -> ChatResult:
    return ChatResult(
        content=content, tool_calls=[], prompt_tokens=0, completion_tokens=0, model="fake"
    )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.workspace.root = str(tmp_path / "ws")
    settings.storage.backups_dir = str(tmp_path / "backups")
    settings.storage.db_path = str(tmp_path / "app.db")
    (tmp_path / "ws").mkdir(parents=True, exist_ok=True)

    state = AppState(settings=settings)
    app = create_app(state)
    c = TestClient(app)
    with c:
        yield c


def wait_task(client: TestClient, task_id: str, timeout: float = 15) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/api/tasks/{task_id}")
        last = r.json()
        if last["status"] in ("done", "stopped", "failed"):
            return last
        time.sleep(0.1)
    raise TimeoutError(f"任务未结束: {last}")


def test_status_and_static(client: TestClient) -> None:
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["model"] == "deepseek-chat"
    assert data["tool_count"] >= 13
    html = client.get("/")
    assert html.status_code == 200
    assert "AgentDesk" in html.text


def test_session_crud_and_export(client: TestClient) -> None:
    sid = client.post("/api/sessions", json={"title": "测试"}).json()["id"]
    sessions = client.get("/api/sessions").json()
    assert any(s["id"] == sid for s in sessions)
    assert client.get(f"/api/sessions/{sid}/messages").json() == []
    md = client.get(f"/api/sessions/{sid}/export").text
    assert "测试" in md
    assert client.delete(f"/api/sessions/{sid}").json()["ok"] is True
    assert client.get("/api/sessions").json() == []


def test_task_flow_completes(client: TestClient) -> None:
    state: AppState = client.app.state.agent
    state.llm_factory = lambda s: FakeLLM([_plan(), _tool("list_files"), _text("完成")])
    sid = client.post("/api/sessions", json={}).json()["id"]
    tid = client.post(f"/api/sessions/{sid}/tasks", json={"request": "列文件"}).json()["task_id"]
    result = wait_task(client, tid)
    assert result["status"] == "done"
    assert result["steps"] == 1
    # 消息已记录
    msgs = client.get(f"/api/sessions/{sid}/messages").json()
    assert any(m["role"] == "user" for m in msgs)


def test_confirm_flow(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "ws" / "existing.txt").write_text("old", encoding="utf-8")
    state: AppState = client.app.state.agent
    write = json.dumps({"path": "existing.txt", "content": "new"})
    state.llm_factory = lambda s: FakeLLM([_plan(), _tool("write_file", write), _text("已覆盖")])

    sid = client.post("/api/sessions", json={}).json()["id"]
    tid = client.post(f"/api/sessions/{sid}/tasks", json={"request": "覆盖文件"}).json()["task_id"]

    pending = None
    deadline = time.time() + 10
    while time.time() < deadline:
        pending = client.get(f"/api/tasks/{tid}/pending").json()
        if pending:
            break
        time.sleep(0.1)
    assert pending is not None, "任务未进入等待确认"

    resp = client.post(f"/api/tasks/{tid}/confirm", json={"call_id": pending["call_id"]})
    assert resp.status_code == 200
    result = wait_task(client, tid)
    assert result["status"] == "done"
    assert (tmp_path / "ws" / "existing.txt").read_text(encoding="utf-8") == "new"
    # 自动备份产生，可恢复
    backups = client.get("/api/backups").json()
    assert any(b["src_rel"] == "existing.txt" for b in backups)


def test_reject_flow(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "ws" / "f.txt").write_text("old", encoding="utf-8")
    state: AppState = client.app.state.agent
    write = json.dumps({"path": "f.txt", "content": "new"})
    state.llm_factory = lambda s: FakeLLM(
        [_plan(), _tool("write_file", write), _text("好的，不覆盖了")]
    )

    sid = client.post("/api/sessions", json={}).json()["id"]
    tid = client.post(f"/api/sessions/{sid}/tasks", json={"request": "覆盖文件"}).json()["task_id"]
    pending = None
    deadline = time.time() + 10
    while time.time() < deadline:
        pending = client.get(f"/api/tasks/{tid}/pending").json()
        if pending:
            break
        time.sleep(0.1)
    assert pending is not None
    client.post(f"/api/tasks/{tid}/reject", json={"call_id": pending["call_id"]})
    result = wait_task(client, tid)
    assert result["status"] == "done"
    assert (tmp_path / "ws" / "f.txt").read_text(encoding="utf-8") == "old"  # 未被覆盖


def test_cancel_flow(client: TestClient) -> None:
    state: AppState = client.app.state.agent
    state.llm_factory = lambda s: FakeLLM(
        [_plan()] + [_tool("list_files") for _ in range(20)], delay=0.05
    )
    sid = client.post("/api/sessions", json={}).json()["id"]
    tid = client.post(f"/api/sessions/{sid}/tasks", json={"request": "长任务"}).json()["task_id"]
    time.sleep(0.2)
    client.post(f"/api/tasks/{tid}/cancel")
    result = wait_task(client, tid)
    assert result["status"] == "stopped"
    assert "取消" in result["summary"]


def test_upload_and_workspace_files(client: TestClient, tmp_path: Path) -> None:
    resp = client.post(
        "/api/upload",
        files={
            "file": (
                "scores.csv",
                "name,score\n张三,88\n".encode(),
                "text/csv",
            )
        },
    )
    assert resp.json()["path"] == "scores.csv"
    data = client.get("/api/workspace/files?path=.").json()
    assert any(e["name"] == "scores.csv" for e in data["entries"])
    assert (tmp_path / "ws" / "scores.csv").exists()


def test_upload_name_traversal_blocked(client: TestClient, tmp_path: Path) -> None:
    client.post(
        "/api/upload",
        files={"file": ("..\\..\\evil.txt", b"x", "text/plain")},
    )
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


def test_restore_api(client: TestClient, tmp_path: Path) -> None:
    settings = load_settings()
    db = DB(db_path=tmp_path / "app.db", settings=settings)
    target = tmp_path / "ws" / "keep.txt"
    target.write_text("orig", encoding="utf-8")
    backup_dir = tmp_path / "backups"
    from agentdesk.storage.backup import BackupManager

    mgr = BackupManager(db, backup_dir, tmp_path / "ws")
    bid = mgr.backup("task1", target)
    assert bid is not None
    target.write_text("changed", encoding="utf-8")
    assert client.post(f"/api/backups/{bid}/restore").json()["ok"] is True
    assert target.read_text(encoding="utf-8") == "orig"


def test_websocket_ping_pong(client: TestClient) -> None:
    with client.websocket_connect("/ws/tasks/nonexistent") as ws:
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"


def test_restart_marks_interrupted_tasks_failed(tmp_path: Path) -> None:
    """服务重启后（runner 内存丢失），running/waiting_confirm 任务应被标记失败，
    避免前端恢复出无法确认的挂起弹窗。"""
    settings = load_settings()
    settings.workspace.root = str(tmp_path / "ws")
    settings.storage.backups_dir = str(tmp_path / "backups")
    settings.storage.db_path = str(tmp_path / "app.db")
    (tmp_path / "ws").mkdir(parents=True, exist_ok=True)

    # 先造一个「上次服务遗留」的挂起任务
    db = DB(settings=settings)
    s = db.create_session()
    t1 = db.create_task(s.id, "挂起任务")
    db.update_task(t1.id, status="waiting_confirm")
    t2 = db.create_task(s.id, "运行中任务")
    db.update_task(t2.id, status="running")
    t3 = db.create_task(s.id, "已完成任务")
    db.update_task(t3.id, status="done")

    # 重新启动（新建 AppState 模拟服务重启）
    state = AppState(settings=settings)
    assert state.db.get_task(t1.id) is not None
    assert state.db.get_task(t1.id).status == "failed"  # type: ignore[union-attr]
    assert state.db.get_task(t2.id).status == "failed"  # type: ignore[union-attr]
    assert state.db.get_task(t3.id).status == "done"  # type: ignore[union-attr]
    assert "服务重启" in state.db.get_task(t1.id).summary  # type: ignore[union-attr]
