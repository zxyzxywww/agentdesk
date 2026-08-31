import { Activity, Bot } from "lucide-react";
import { fmtCost } from "@/lib/utils";
import type { StatusInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TopBar({
  status,
  running,
  cost,
}: {
  status: StatusInfo | null;
  running: boolean;
  cost: number;
}) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-card/80 px-4 backdrop-blur">
      <div className="flex items-center gap-2.5">
        <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Bot className="size-4" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">AgentDesk</div>
          <div className="text-[9px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Task Agent
          </div>
        </div>
      </div>

      {/* Agent 心跳 */}
      <div
        className={cn(
          "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors",
          running
            ? "border-primary/40 bg-primary/5 text-primary"
            : "border-border text-muted-foreground"
        )}
      >
        <span
          className={cn(
            "size-1.5 rounded-full",
            running ? "animate-pulse bg-primary" : "bg-muted-foreground/50"
          )}
        />
        {running ? "Agent 运行中" : "空闲"}
      </div>

      <div
        className="ml-2 hidden items-center gap-1.5 text-[11px] text-muted-foreground xl:flex"
        title="模型 · 搜索服务 · 工作目录"
      >
        <span className="font-mono">{status?.model ?? "…"}</span>
        <span className="opacity-50">·</span>
        <span className="font-mono">{status?.search_provider ?? "…"}</span>
        <span className="opacity-50">·</span>
        <span className="max-w-[200px] truncate">{status?.workspace}</span>
      </div>

      <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
        <Activity className="size-3.5" />
        累计成本
        <span className="font-mono font-semibold text-foreground">{fmtCost(cost)}</span>
      </div>
    </header>
  );
}
