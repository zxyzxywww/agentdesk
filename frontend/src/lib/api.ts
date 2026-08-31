import type {
  BackupRecord,
  Message,
  PendingConfirm,
  Session,
  StatusInfo,
  TaskRecord,
  TaskResult,
  WorkspaceListing,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error((await res.text()) || `请求失败: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

export const api = {
  status: () => request<StatusInfo>("/api/status"),

  sessions: {
    list: () => request<Session[]>("/api/sessions"),
    create: (title = "新会话") =>
      request<Session>("/api/sessions", {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ title }),
      }),
    remove: (id: string) =>
      request<{ ok: boolean }>(`/api/sessions/${id}`, { method: "DELETE" }),
    rename: (id: string, title: string) =>
      request<Session>(`/api/sessions/${id}`, {
        method: "PATCH",
        headers: jsonHeaders,
        body: JSON.stringify({ title }),
      }),
    messages: (id: string) => request<Message[]>(`/api/sessions/${id}/messages`),
    tasks: (id: string) => request<TaskRecord[]>(`/api/sessions/${id}/tasks`),
    exportMarkdown: async (id: string) => {
      const res = await fetch(`/api/sessions/${id}/export?fmt=md`);
      return res.text();
    },
  },

  tasks: {
    create: (sessionId: string, text: string) =>
      request<{ task_id: string; status: string }>(
        `/api/sessions/${sessionId}/tasks`,
        { method: "POST", headers: jsonHeaders, body: JSON.stringify({ request: text }) }
      ),
    result: (id: string) => request<TaskResult>(`/api/tasks/${id}`),
    pending: (id: string) =>
      request<PendingConfirm | null>(`/api/tasks/${id}/pending`),
    confirm: (id: string, callId: number) =>
      request<{ status: string }>(`/api/tasks/${id}/confirm`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ call_id: callId }),
      }),
    reject: (id: string, callId: number) =>
      request<{ status: string }>(`/api/tasks/${id}/reject`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({ call_id: callId }),
      }),
    cancel: (id: string) =>
      request<{ status: string }>(`/api/tasks/${id}/cancel`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({}),
      }),
  },

  backups: {
    list: () => request<BackupRecord[]>("/api/backups"),
    restore: (id: number) =>
      request<{ ok: boolean }>(`/api/backups/${id}/restore`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({}),
      }),
  },

  workspace: {
    files: (path = ".") =>
      request<WorkspaceListing>(
        `/api/workspace/files?path=${encodeURIComponent(path)}`
      ),
    upload: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch("/api/upload", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<{ path: string; size: number }>;
    },
  },
};
