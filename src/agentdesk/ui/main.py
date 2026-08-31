"""FastAPI Web 后端：REST API + WebSocket 实时事件流 + 静态前端。

- REST：会话/消息/任务/验收/备份撤销/上传/导出/状态
- WebSocket /ws/tasks/{task_id}：实时推送 AgentEvent（工具状态流、需确认、完成）
- Agent 在后台线程执行；事件经事件循环转发到对应任务的 WS 连接
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentdesk.config import Settings, get_settings
from agentdesk.core.executor import AgentEvent, AgentPaused, AgentRunner
from agentdesk.core.export import export_session_markdown, markdown_to_html
from agentdesk.core.planner import Planner
from agentdesk.core.summary import pending_confirmation, task_result
from agentdesk.llm.client import LLMClient
from agentdesk.storage.backup import BackupManager
from agentdesk.storage.db import DB
from agentdesk.tools import build_default_tools
from agentdesk.tools.registry import ToolContext, ToolRegistry

# 前端构建产物（Vite + React + Tailwind），由 FastAPI 直接托管
FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


class CreateSession(BaseModel):
    title: str = "新会话"


class RenameSession(BaseModel):
    title: str


class TaskRequest(BaseModel):
    request: str


class ConfirmRequest(BaseModel):
    call_id: int


class AppState:
    """应用级共享状态（可注入工厂便于测试）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = DB(settings=self.settings)
        self._mark_interrupted_tasks()
        self.registry = ToolRegistry(build_default_tools())
        self.runners: dict[str, AgentRunner] = {}
        self.ws_clients: dict[str, set[WebSocket]] = {}
        self.llm_clients: dict[str, LLMClient] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.llm_factory: Callable[[Settings], LLMClient] = lambda s: LLMClient(s)
        self.planner_factory: Callable[[LLMClient, Settings], Planner] = Planner

    def _mark_interrupted_tasks(self) -> None:
        """服务重启后，内存 runner 已丢失：把 running/waiting_confirm 的任务标记为失败，
        避免前端恢复出「无法确认」的挂起弹窗。"""
        for task in self.db.list_all_tasks():
            if task.status in ("running", "waiting_confirm"):
                self.db.update_task(
                    task.id,
                    status="failed",
                    summary=(
                        f"任务中断：服务重启后无法继续（原状态 {task.status}），"
                        "请重新发起任务。"
                    ),
                )

    def llm_for(self, session_id: str) -> LLMClient:
        if session_id not in self.llm_clients:
            self.llm_clients[session_id] = self.llm_factory(self.settings)
        return self.llm_clients[session_id]

    def backups(self) -> BackupManager:
        return BackupManager(
            self.db, self.settings.backups_dir_abs, self.settings.workspace_root
        )

    async def broadcast(self, task_id: str, event: AgentEvent) -> None:
        payload = {"type": event.type, "data": event.data, "task_id": event.task_id}
        for ws in list(self.ws_clients.get(task_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001 - 连接失效则摘除
                self.ws_clients.get(task_id, set()).discard(ws)

    def on_event(self, event: AgentEvent) -> None:
        """Agent 线程的同步回调 → 投递到事件循环推送 WS。"""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(
                self.broadcast(event.task_id, event), self.loop
            )


def _run_agent(state: AppState, runner: AgentRunner) -> None:
    try:
        runner.run()
        state.runners.pop(runner.task_id, None)
    except AgentPaused:
        pass  # 保留 runner，等待用户 confirm
    except Exception as e:  # noqa: BLE001
        state.on_event(
            AgentEvent(type="error", task_id=runner.task_id, data={"error": str(e)})
        )
        state.runners.pop(runner.task_id, None)


def _confirm_agent(state: AppState, runner: AgentRunner, call_id: int) -> None:
    try:
        runner.confirm(call_id)
    except AgentPaused:
        pass  # 又遇到需确认的危险操作，保留 runner，等待下一次 confirm/reject
    except Exception as e:  # noqa: BLE001
        state.on_event(
            AgentEvent(type="error", task_id=runner.task_id, data={"error": str(e)})
        )
        state.runners.pop(runner.task_id, None)
    else:
        state.runners.pop(runner.task_id, None)


def create_app(state: AppState | None = None) -> FastAPI:
    if state is None:
        state = AppState()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.loop = asyncio.get_running_loop()
        yield

    app = FastAPI(title="AgentDesk", lifespan=lifespan)
    app.state.agent = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- 页面与静态资源 ----------

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        """返回前端 SPA（frontend/dist 构建产物）；未构建时给出提示。"""
        html_file = FRONTEND_DIST / "index.html"
        if html_file.exists():
            return html_file.read_text(encoding="utf-8")
        return (
            "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<title>AgentDesk</title></head>"
            "<body style='font-family:system-ui,sans-serif;padding:2.5rem;line-height:1.7'>"
            "<h2>AgentDesk</h2>"
            "<p>前端尚未构建：请先在 <code>frontend/</code> 目录执行 "
            "<code>npm install</code> 与 <code>npm run build</code>。</p>"
            "</body></html>"
        )

    # ---------- 状态 ----------

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return {
            "model": state.settings.model.chat_model,
            "base_url": state.settings.model.base_url,
            "search_provider": state.settings.search.provider,
            "workspace": str(state.settings.workspace_root),
            "tool_count": len(state.registry.names()),
            "tools": state.registry.names(),
        }

    # ---------- 会话 ----------

    @app.get("/api/sessions")
    def api_sessions() -> list[dict[str, Any]]:
        return [s.__dict__ for s in state.db.list_sessions()]

    @app.post("/api/sessions")
    def api_create_session(payload: CreateSession) -> dict[str, Any]:
        s = state.db.create_session(
            title=payload.title, workspace=str(state.settings.workspace_root)
        )
        return s.__dict__

    @app.delete("/api/sessions/{sid}")
    def api_delete_session(sid: str) -> dict[str, Any]:
        if state.db.get_session(sid) is None:
            raise HTTPException(404, "会话不存在")
        state.db.delete_session(sid)
        return {"ok": True}

    @app.patch("/api/sessions/{sid}")
    def api_rename_session(sid: str, payload: RenameSession) -> dict[str, Any]:
        if state.db.get_session(sid) is None:
            raise HTTPException(404, "会话不存在")
        if not payload.title.strip():
            raise HTTPException(400, "标题不能为空")
        state.db.rename_session(sid, payload.title.strip())
        s = state.db.get_session(sid)
        assert s is not None
        return s.__dict__

    @app.get("/api/sessions/{sid}/messages")
    def api_messages(sid: str) -> list[dict[str, Any]]:
        return [m.__dict__ for m in state.db.list_messages(sid)]

    @app.get("/api/sessions/{sid}/tasks")
    def api_tasks(sid: str) -> list[dict[str, Any]]:
        return [t.__dict__ for t in state.db.list_tasks(sid)]

    # ---------- 任务 ----------

    @app.post("/api/sessions/{sid}/tasks")
    def api_create_task(sid: str, payload: TaskRequest) -> dict[str, Any]:
        if state.db.get_session(sid) is None:
            raise HTTPException(404, "会话不存在")
        if not payload.request.strip():
            raise HTTPException(400, "任务描述不能为空")
        task = state.db.create_task(sid, payload.request.strip())
        llm = state.llm_for(sid)
        runner = AgentRunner(
            task_id=task.id,
            session_id=sid,
            user_request=payload.request.strip(),
            registry=state.registry,
            llm=llm,
            planner=state.planner_factory(llm, state.settings),
            db=state.db,
            settings=state.settings,
            on_event=state.on_event,
        )
        state.runners[task.id] = runner
        threading.Thread(
            target=_run_agent, args=(state, runner), daemon=True
        ).start()
        return {"task_id": task.id, "status": "running"}

    @app.get("/api/tasks/{tid}")
    def api_task(tid: str) -> dict[str, Any]:
        try:
            return task_result(state.db, tid)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/tasks/{tid}/pending")
    def api_pending(tid: str) -> dict[str, Any] | None:
        return pending_confirmation(state.db, tid)

    @app.post("/api/tasks/{tid}/confirm")
    def api_confirm(tid: str, payload: ConfirmRequest) -> dict[str, Any]:
        runner = state.runners.get(tid)
        if runner is None:
            raise HTTPException(404, "任务不存在或未在等待确认")
        threading.Thread(
            target=_confirm_agent, args=(state, runner, payload.call_id), daemon=True
        ).start()
        return {"status": "confirming"}

    @app.post("/api/tasks/{tid}/reject")
    def api_reject(tid: str, payload: ConfirmRequest) -> dict[str, Any]:
        runner = state.runners.get(tid)
        if runner is None:
            raise HTTPException(404, "任务不存在或未在等待确认")

        def _reject_agent() -> None:
            try:
                runner.reject(payload.call_id)
            except AgentPaused:
                pass  # 拒绝后又遇到新确认，保留 runner
            except Exception as e:  # noqa: BLE001
                state.on_event(
                    AgentEvent(
                        type="error", task_id=runner.task_id, data={"error": str(e)}
                    )
                )
                state.runners.pop(runner.task_id, None)
            else:
                state.runners.pop(runner.task_id, None)

        threading.Thread(target=_reject_agent, daemon=True).start()
        return {"status": "rejecting"}

    @app.post("/api/tasks/{tid}/cancel")
    def api_cancel(tid: str) -> dict[str, Any]:
        runner = state.runners.get(tid)
        if runner is None:
            raise HTTPException(404, "任务不存在或已结束")
        runner.cancel()
        return {"status": "cancelling"}

    # ---------- 备份 / 撤销 ----------

    @app.get("/api/backups")
    def api_backups() -> list[dict[str, Any]]:
        return [b.__dict__ for b in state.db.list_backups()]

    @app.post("/api/backups/{bid}/restore")
    def api_restore(bid: int) -> dict[str, Any]:
        ok = state.backups().restore(bid)
        if not ok:
            raise HTTPException(400, "恢复失败：备份不存在或文件已丢失")
        return {"ok": True}

    # ---------- 工作目录 ----------

    @app.get("/api/workspace/files")
    def api_workspace_files(path: str = ".") -> dict[str, Any]:
        ctx = ToolContext(state.settings.workspace_root, state.settings)
        try:
            r = state.registry.execute("list_files", {"path": path}, ctx)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, str(e)) from e
        return r.data if r.data else {}

    @app.post("/api/upload")
    async def api_upload(file: UploadFile) -> dict[str, Any]:
        name = Path(file.filename or "upload.bin").name  # 仅取文件名，防路径穿越
        target = state.settings.workspace_root / name
        content = await file.read()
        target.write_bytes(content)
        return {"path": name, "size": len(content)}

    # ---------- 导出 ----------

    @app.get("/api/sessions/{sid}/export")
    def api_export(sid: str, fmt: str = "md") -> Response:
        try:
            md = export_session_markdown(state.db, sid)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        if fmt == "html":
            return HTMLResponse(markdown_to_html(md))
        return Response(md, media_type="text/markdown; charset=utf-8")

    # ---------- WebSocket 实时事件流 ----------

    @app.websocket("/ws/tasks/{tid}")
    async def ws_task(ws: WebSocket, tid: str) -> None:
        await ws.accept()
        state.ws_clients.setdefault(tid, set()).add(ws)
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            state.ws_clients.get(tid, set()).discard(ws)

    # ---------- 静态资源 ----------

    if FRONTEND_DIST.exists():
        app.mount(
            "/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets"
        )
    return app
