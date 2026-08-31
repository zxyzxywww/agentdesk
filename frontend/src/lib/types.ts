// 与后端 REST / WebSocket 对齐的类型

export interface Session {
  id: string;
  title: string;
  workspace: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export type TaskStatus =
  | "pending"
  | "running"
  | "waiting_confirm"
  | "done"
  | "stopped"
  | "failed";

export interface TaskRecord {
  id: string;
  session_id: string;
  user_request: string;
  status: TaskStatus;
  plan_json: string;
  summary: string;
  cost_yuan: number;
  steps: number;
  created_at: string;
  updated_at: string;
}

export interface ToolCallInfo {
  name: string;
  status: string;
  duration_s: number;
  arguments: Record<string, unknown>;
  result: Record<string, unknown> | null;
}

export interface PlanStep {
  goal: string;
  tool: string | null;
  note: string;
}

export interface TaskResult {
  id: string;
  user_request: string;
  status: TaskStatus;
  summary: string;
  steps: number;
  cost_yuan: number;
  plan: PlanStep[];
  files: string[];
  tool_calls: ToolCallInfo[];
}

export interface BackupRecord {
  id: number;
  task_id: string;
  op: string;
  src_rel: string;
  backup_path: string;
  restored: number;
  created_at: string;
}

export interface WorkspaceEntry {
  name: string;
  type: "dir" | "file";
  size: number;
  modified: string;
}

export interface WorkspaceListing {
  path: string;
  entries: WorkspaceEntry[];
  truncated: boolean;
}

export interface StatusInfo {
  model: string;
  base_url: string;
  search_provider: string;
  workspace: string;
  tool_count: number;
  tools: string[];
}

export type AgentEventType =
  | "plan"
  | "tool_start"
  | "tool_end"
  | "message"
  | "needs_confirm"
  | "done"
  | "stopped"
  | "error";

export interface AgentEvent {
  type: AgentEventType;
  task_id: string;
  data: Record<string, unknown>;
}

export interface PendingConfirm {
  call_id: number;
  name: string;
  arguments: Record<string, unknown>;
}
