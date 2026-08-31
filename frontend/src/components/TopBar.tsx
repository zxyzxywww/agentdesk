import { Activity, Bot, FolderOpen, Search } from "lucide-react";
import { Badge } from "./ui/badge";
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

      <div className="ml-2 hidden items-center gap-1.5 lg:flex">
        <Badge variant="secondary" className="gap-1 font-normal" title="当前网页搜索使用的服务">
          <Search className="size-3" />
          <span className="text-muted-foreground">搜索</span>
          {status?.search_provider ?? "…"}
        </Badge>
        <Badge variant="secondary" className="max-w-[260px] gap-1 truncate font-normal" title={status?.workspace}>
          <FolderOpen className="size-3 shrink-0" />
          <span className="truncate">{status?.workspace}</span>
        </Badge>
      </div>

      <div className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
        <Activity className="size-3.5" />
        累计成本
        <span className="font-mono font-semibold text-foreground">{fmtCost(cost)}</span>
      </div>
    </header>
  );
}
