import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { TopBar } from "./components/TopBar";
import { SessionList } from "./components/SessionList";
import { Chat } from "./components/Chat";
import { Composer } from "./components/Composer";
import { RightPanel, type PanelTab } from "./components/RightPanel";
import { ConfirmDialog } from "./components/ConfirmDialog";
import type { ToolCardData } from "./components/panels/ToolLog";
import { api } from "./lib/api";
import { useTaskSocket } from "./lib/ws";
import type {
  AgentEvent,
  BackupRecord,
  Message,
  PendingConfirm,
  PlanStep,
  Session,
  StatusInfo,
  TaskResult,
  WorkspaceEntry,
} from "./lib/types";

export default function App() {
  // ---- 顶部与会话 ----
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [cost, setCost] = useState(0);

  // ---- 右侧面板 ----
  const [tab, setTab] = useState<PanelTab>("run");
  const [toolCards, setToolCards] = useState<ToolCardData[]>([]);
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [accept, setAccept] = useState<TaskResult | null>(null);
  const [files, setFiles] = useState<WorkspaceEntry[]>([]);
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const msgSeq = useRef(0);
  const appendMessage = useCallback((role: "user" | "assistant", content: string) => {
    msgSeq.current += 1;
    setMessages((prev) => [
      ...prev,
      { id: -msgSeq.current, session_id: "", role, content, created_at: "" },
    ]);
  }, []);

  // ---- 加载辅助 ----
  const loadFiles = useCallback(async () => {
    try {
      const r = await api.workspace.files();
      setFiles(r.entries ?? []);
    } catch (e) {
      toast.error("加载文件失败: " + (e as Error).message);
    }
  }, []);

  const loadBackups = useCallback(async () => {
    try {
      setBackups(await api.backups.list());
    } catch {
      /* 忽略 */
    }
  }, []);

  const loadCost = useCallback(async (sessionId?: string) => {
    const sid = sessionId ?? currentSession?.id;
    if (!sid) return;
    try {
      const tasks = await api.sessions.tasks(sid);
      setCost(tasks.reduce((s, t) => s + (t.cost_yuan || 0), 0));
    } catch {
      /* 忽略 */
    }
  }, [currentSession?.id]);

  const loadSessions = useCallback(async () => {
    const list = await api.sessions.list();
    setSessions(list);
    return list;
  }, []);

  // ---- 面板恢复：从已完成的任务结果填充 执行/计划/验收 ----
  const restorePanel = useCallback(async (taskId: string) => {
    try {
      const r = await api.tasks.result(taskId);
      setAccept(r);
      setPlan(r.plan ?? []);
      setToolCards(
        (r.tool_calls ?? []).map((c, i) => ({
          seq: i + 1,
          name: c.name,
          status: (
            c.status === "success" ? "success" : c.status === "failed" ? "failed" : "waiting_confirm"
          ) as ToolCardData["status"],
          args: c.arguments,
          summary:
            typeof c.result?.path === "string"
              ? `产出: ${c.result.path}`
              : undefined,
          files:
            typeof c.result?.path === "string" ? [c.result.path as string] : undefined,
          duration: c.duration_s,
        }))
      );
    } catch {
      /* 忽略 */
    }
  }, []);

  // ---- 会话切换 ----
  const selectSession = useCallback(
    async (session: Session) => {
      const id = session.id;
      setCurrentSession(session);
      setTaskId(null);
      setRunning(false);
      setPending(null);
      setToolCards([]);
      setPlan([]);
      setAccept(null);
      try {
        setMessages(await api.sessions.messages(id));
      } catch (e) {
        // 失败时清空并提示，避免显示上一个会话的消息造成张冠李戴
        setMessages([]);
        toast.error("加载会话消息失败：" + (e as Error).message);
      }
      await Promise.all([loadFiles(), loadBackups(), loadCost(id)]);
      // 恢复挂起确认，或最近已完成任务的面板状态（刷新/切换不丢历史）
      try {
        const tasks = await api.sessions.tasks(id);
        const hanging = tasks.find((t) => t.status === "waiting_confirm");
        if (hanging) {
          setTaskId(hanging.id);
          const p = await api.tasks.pending(hanging.id);
          if (p) setPending(p);
        } else {
          const lastDone = [...tasks]
            .reverse()
            .find((t) => ["done", "stopped", "failed"].includes(t.status));
          if (lastDone) await restorePanel(lastDone.id);
        }
      } catch {
        /* 忽略 */
      }
    },
    [loadFiles, loadBackups, loadCost, restorePanel]
  );

  // ---- 任务结束后的验收刷新 ----
  const finishTask = useCallback(
    async (tid: string) => {
      try {
        setAccept(await api.tasks.result(tid));
      } catch {
        /* 忽略 */
      }
      await Promise.all([loadFiles(), loadBackups(), loadCost()]);
    },
    [loadFiles, loadBackups, loadCost]
  );

  // ---- 实时事件 ----
  const handleEvent = useCallback(
    (e: AgentEvent) => {
      switch (e.type) {
        case "plan":
          setPlan((e.data.plan as PlanStep[]) ?? []);
          break;
        case "tool_start": {
          const d = e.data as { name: string; args: Record<string, unknown>; seq: number };
          setToolCards((prev) => [
            ...prev,
            { seq: d.seq, name: d.name, status: "start", args: d.args },
          ]);
          break;
        }
        case "tool_end": {
          const d = e.data as {
            name: string;
            status: "success" | "failed" | "waiting_confirm";
            summary?: string;
            files?: string[];
            duration?: number;
            seq: number;
          };
          setToolCards((prev) =>
            prev.map((c) =>
              c.seq === d.seq
                ? { ...c, status: d.status, summary: d.summary, files: d.files, duration: d.duration }
                : c
            )
          );
          break;
        }
        case "needs_confirm": {
          const d = e.data as { call_id: number };
          setPending({ call_id: d.call_id, name: "…", arguments: {} });
          if (taskId) {
            api.tasks.pending(taskId).then((p) => p && setPending(p)).catch(() => {});
          }
          break;
        }
        case "message":
          appendMessage("assistant", String(e.data.content ?? ""));
          break;
        case "done":
        case "stopped": {
          setRunning(false);
          appendMessage(
            "assistant",
            String(e.data.summary ?? (e.type === "done" ? "任务完成 ✅" : "任务已停止"))
          );
          if (taskId) void finishTask(taskId);
          break;
        }
        case "error": {
          setRunning(false);
          appendMessage("assistant", "⚠ " + String(e.data.error ?? ""));
          break;
        }
      }
    },
    [taskId, appendMessage, finishTask]
  );

  useTaskSocket(running ? taskId : null, handleEvent);

  // ---- 动作 ----
  const sendTask = useCallback(
    async (text: string) => {
      let sid = currentSession?.id;
      if (!sid) {
        const s = await api.sessions.create();
        sid = s.id;
        const list = await loadSessions();
        const created = list.find((x) => x.id === sid);
        setCurrentSession(created ?? s);
      }
      appendMessage("user", text);
      setRunning(true);
      setToolCards([]);
      setPlan([]);
      setAccept(null);
      try {
        const res = await api.tasks.create(sid, text);
        setTaskId(res.task_id);
      } catch (e) {
        appendMessage("assistant", "⚠ 任务启动失败：" + (e as Error).message);
        setRunning(false);
      }
    },
    [currentSession?.id, appendMessage, loadSessions]
  );

  const stopTask = useCallback(async () => {
    if (taskId) {
      try {
        await api.tasks.cancel(taskId);
      } catch {
        /* 忽略 */
      }
    }
  }, [taskId]);

  const confirmTask = useCallback(
    async (callId: number) => {
      setPending(null);
      if (!taskId) return;
      try {
        await api.tasks.confirm(taskId, callId);
      } catch (e) {
        const msg = (e as Error).message;
        toast.error(
          msg.includes("不存在") || msg.includes("404")
            ? "该任务已失效（服务可能重启过），请重新发起任务"
            : "确认失败：" + msg
        );
        setRunning(false);
        setTaskId(null);
      }
    },
    [taskId]
  );

  const rejectTask = useCallback(
    async (callId: number) => {
      setPending(null);
      if (!taskId) return;
      try {
        await api.tasks.reject(taskId, callId);
      } catch (e) {
        const msg = (e as Error).message;
        toast.error(
          msg.includes("不存在") || msg.includes("404")
            ? "该任务已失效（服务可能重启过），请重新发起任务"
            : "操作失败：" + msg
        );
        setRunning(false);
        setTaskId(null);
      }
    },
    [taskId]
  );

  const restoreBackup = useCallback(
    async (id: number) => {
      try {
        await api.backups.restore(id);
        toast.success("已恢复备份");
        await Promise.all([loadBackups(), loadFiles()]);
      } catch (e) {
        toast.error("恢复失败：" + (e as Error).message);
      }
    },
    [loadBackups, loadFiles]
  );

  const exportReport = useCallback(async () => {
    if (!currentSession) return;
    const md = await api.sessions.exportMarkdown(currentSession.id);
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `agentdesk-report-${currentSession.id}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, [currentSession]);

  // ---- 初始化 ----
  useEffect(() => {
    (async () => {
      try {
        setStatus(await api.status());
        const list = await loadSessions();
        if (list.length) await selectSession(list[0]);
      } catch (e) {
        toast.error("后端初始化失败：" + (e as Error).message);
      }
    })();
  }, [loadSessions, selectSession]);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar status={status} running={running} cost={cost} />
      <div className="flex flex-1 overflow-hidden">
        <SessionList
          sessions={sessions}
          currentId={currentSession?.id ?? null}
          onSelect={selectSession}
          onCreate={async () => {
            try {
              const s = await api.sessions.create();
              await loadSessions();
              await selectSession(s);
              toast.success("已创建新会话");
            } catch (e) {
              toast.error("新建会话失败：" + (e as Error).message);
            }
          }}
          onDelete={async (id) => {
            await api.sessions.remove(id);
            if (currentSession?.id === id) setCurrentSession(null);
            await loadSessions();
          }}
          onRename={async (id, title) => {
            try {
              await api.sessions.rename(id, title);
              await loadSessions();
              setCurrentSession((prev) =>
                prev && prev.id === id ? { ...prev, title } : prev
              );
            } catch (e) {
              toast.error("重命名失败：" + (e as Error).message);
            }
          }}
          onExport={exportReport}
        />
        <main className="flex min-w-0 flex-1 flex-col">
          <Chat messages={messages} />
          <Composer running={running} onSend={sendTask} onStop={stopTask} />
        </main>
        <RightPanel
          tab={tab}
          onTabChange={setTab}
          toolCards={toolCards}
          plan={plan}
          files={files}
          accept={accept}
          backups={backups}
          onRestore={restoreBackup}
        />
      </div>
      <ConfirmDialog pending={pending} onConfirm={confirmTask} onReject={rejectTask} />
    </div>
  );
}
