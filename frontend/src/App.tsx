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
import { useDrag } from "./lib/useDrag";
import { clamp } from "./lib/utils";
import type {
  AgentEvent,
  BackupRecord,
  Message,
  PendingConfirm,
  PlanStep,
  Session,
  StatusInfo,
  TaskResult,
} from "./lib/types";

// 三区域尺寸范围与默认值
const LAYOUT_KEY = "agentdesk.layout";
const LEFT = { min: 180, max: 420, def: 240 };
const RIGHT = { min: 300, max: 650, def: 400 };
const BOTTOM = { min: 130, max: 400, def: 200 };

function loadLayout() {
  let left = LEFT.def;
  let right = RIGHT.def;
  let bottom = BOTTOM.def;
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Record<string, number>;
      left = clamp(Number(p.left) || LEFT.def, LEFT.min, LEFT.max);
      right = clamp(Number(p.right) || RIGHT.def, RIGHT.min, RIGHT.max);
      bottom = clamp(Number(p.bottom) || BOTTOM.def, BOTTOM.min, BOTTOM.max);
    }
  } catch {
    /* 忽略损坏数据 */
  }
  return { left, right, bottom };
}

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
  const [refreshKey, setRefreshKey] = useState(0); // 文件面板刷新信号
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [pending, setPending] = useState<PendingConfirm | null>(null);

  const msgSeq = useRef(0);
  const sessionRef = useRef<Session | null>(null);
  const selectSeq = useRef(0);
  const didInit = useRef(false);

  // ---- 三区域可拖拽布局：尺寸状态 + 持久化 ----
  const [layout, setLayout] = useState(loadLayout);
  const setLeft = useCallback(
    (d: number) => setLayout((l) => ({ ...l, left: clamp(l.left + d, LEFT.min, LEFT.max) })),
    []
  );
  const setRight = useCallback(
    (d: number) => setLayout((l) => ({ ...l, right: clamp(l.right - d, RIGHT.min, RIGHT.max) })),
    []
  );
  const setBottom = useCallback(
    (d: number) => setLayout((l) => ({ ...l, bottom: clamp(l.bottom - d, BOTTOM.min, BOTTOM.max) })),
    []
  );
  const leftDrag = useDrag("x", setLeft);
  const rightDrag = useDrag("x", setRight);
  const bottomDrag = useDrag("y", setBottom);
  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch {
      /* 忽略 */
    }
  }, [layout]);

  const appendMessage = useCallback((role: "user" | "assistant", content: string) => {
    msgSeq.current += 1;
    setMessages((prev) => [
      ...prev,
      { id: -msgSeq.current, session_id: "", role, content, created_at: "" },
    ]);
  }, []);

  // ---- 加载辅助 ----
  const loadBackups = useCallback(async () => {
    try {
      setBackups(await api.backups.list());
    } catch {
      /* 忽略 */
    }
  }, []);

  const loadCost = useCallback(async () => {
    const sid = sessionRef.current?.id;
    if (!sid) return;
    try {
      const tasks = await api.sessions.tasks(sid);
      setCost(tasks.reduce((s, t) => s + (t.cost_yuan || 0), 0));
    } catch {
      /* 忽略 */
    }
  }, []);

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
      const seq = ++selectSeq.current; // 竞态守卫：快速切换时丢弃过期响应
      sessionRef.current = session;
      setCurrentSession(session);
      setTaskId(null);
      setRunning(false);
      setPending(null);
      setToolCards([]);
      setPlan([]);
      setAccept(null);
      try {
        const msgs = await api.sessions.messages(id);
        if (seq !== selectSeq.current) return;
        setMessages(msgs);
      } catch (e) {
        if (seq !== selectSeq.current) return;
        // 失败时清空并提示，避免显示上一个会话的消息造成张冠李戴
        setMessages([]);
        toast.error("加载会话消息失败：" + (e as Error).message);
      }
      if (seq !== selectSeq.current) return;
      setRefreshKey((k) => k + 1);
      await Promise.all([loadBackups(), loadCost()]);
      if (seq !== selectSeq.current) return;
      // 恢复挂起确认，或最近已完成任务的面板状态（刷新/切换不丢历史）
      try {
        const tasks = await api.sessions.tasks(id);
        if (seq !== selectSeq.current) return;
        const hanging = tasks.find((t) => t.status === "waiting_confirm");
        if (hanging) {
          setTaskId(hanging.id);
          const p = await api.tasks.pending(hanging.id);
          if (seq === selectSeq.current && p) setPending(p);
        } else {
          const lastDone = [...tasks]
            .reverse()
            .find((t) => ["done", "stopped", "failed"].includes(t.status));
          if (seq === selectSeq.current && lastDone) await restorePanel(lastDone.id);
        }
      } catch {
        /* 忽略 */
      }
    },
    [loadBackups, loadCost, restorePanel]
  );

  // ---- 任务结束后的验收刷新 ----
  const finishTask = useCallback(
    async (tid: string) => {
      try {
        setAccept(await api.tasks.result(tid));
      } catch {
        /* 忽略 */
      }
      setRefreshKey((k) => k + 1);
      await Promise.all([loadBackups(), loadCost()]);
    },
    [loadBackups, loadCost]
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
          // 最终答复已由 message 事件提供，这里不再 append，避免重复
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
        setRefreshKey((k) => k + 1);
        await loadBackups();
      } catch (e) {
        toast.error("恢复失败：" + (e as Error).message);
      }
    },
    [loadBackups]
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

  // ---- 初始化（仅一次；didInit 守卫防 StrictMode 双执行） ----
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
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
        <div className="relative shrink-0" style={{ width: layout.left }}>
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
          <div
            onPointerDown={leftDrag}
            data-resize="left"
            className="absolute right-0 inset-y-0 w-1.5 cursor-col-resize transition-colors hover:bg-primary/40"
            title="拖拽调整会话栏宽度"
          />
        </div>
        <main className="flex min-w-0 flex-1 flex-col">
          <Chat messages={messages} />
          <Composer
            running={running}
            height={layout.bottom}
            onResizeStart={bottomDrag}
            onSend={sendTask}
            onStop={stopTask}
          />
        </main>
        <div className="relative shrink-0" style={{ width: layout.right }}>
          <RightPanel
            tab={tab}
            onTabChange={setTab}
            toolCards={toolCards}
            plan={plan}
            refreshKey={refreshKey}
            accept={accept}
            backups={backups}
            onRestore={restoreBackup}
          />
          <div
            onPointerDown={rightDrag}
            data-resize="right"
            className="absolute left-0 inset-y-0 w-1.5 -translate-x-1/2 cursor-col-resize transition-colors hover:bg-primary/40"
            title="拖拽调整执行面板宽度"
          />
        </div>
      </div>
      <ConfirmDialog pending={pending} onConfirm={confirmTask} onReject={rejectTask} />
    </div>
  );
}
