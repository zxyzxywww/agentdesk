import { Download, MessageSquarePlus, Plus } from "lucide-react";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";
import type { Session } from "@/lib/types";

export function SessionList({
  sessions,
  currentId,
  onSelect,
  onCreate,
  onDelete,
  onExport,
}: {
  sessions: Session[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onExport: () => void;
}) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r bg-card/50">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          会话
        </span>
        <Button size="sm" variant="outline" onClick={onCreate}>
          <Plus className="size-3.5" />
          新建
        </Button>
      </div>

      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
        {sessions.length === 0 && (
          <div className="px-2 py-8 text-center text-xs text-muted-foreground">
            还没有会话
            <br />
            点上方「新建」开始
          </div>
        )}
        {sessions.map((s) => {
          const active = s.id === currentId;
          return (
            <div
              key={s.id}
              onClick={() => onSelect(s.id)}
              className={cn(
                "group relative flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
                active
                  ? "bg-secondary font-medium text-foreground"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
              )}
            >
              <MessageSquarePlus className="size-3.5 shrink-0 opacity-60" />
              <span className="flex-1 truncate">{s.title}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.id);
                }}
                className="rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                title="删除会话"
              >
                <Plus className="size-3.5 rotate-45" />
              </button>
              {active && (
                <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary" />
              )}
            </div>
          );
        })}
      </div>

      <div className="border-t p-2">
        <Button variant="outline" size="sm" className="w-full" onClick={onExport}>
          <Download className="size-3.5" />
          导出报告
        </Button>
      </div>
    </aside>
  );
}
