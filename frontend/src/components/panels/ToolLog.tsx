import { motion } from "motion/react";
import { Badge } from "../ui/badge";
import { cn } from "@/lib/utils";

export interface ToolCardData {
  seq: number;
  name: string;
  status: "start" | "success" | "failed" | "waiting_confirm";
  args?: Record<string, unknown>;
  summary?: string;
  files?: string[];
  duration?: number;
}

const STATUS_META: Record<ToolCardData["status"], { label: string; variant: "default" | "success" | "destructive" | "warning"; pulsing?: boolean }> = {
  start: { label: "执行中", variant: "default", pulsing: true },
  success: { label: "成功", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
  waiting_confirm: { label: "待确认", variant: "warning", pulsing: true },
};

function ToolCard({ card }: { card: ToolCardData }) {
  const meta = STATUS_META[card.status];
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="rounded-lg border-l-2 bg-card p-3 shadow-sm transition-shadow hover:shadow"
      style={{
        borderLeftColor:
          card.status === "start"
            ? "var(--color-primary)"
            : card.status === "success"
              ? "var(--color-success)"
              : card.status === "failed"
                ? "var(--color-destructive)"
                : "var(--color-warning)",
      }}
    >
      <div className="flex items-center gap-2">
        <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs font-semibold">
          {card.name}
        </code>
        <Badge variant={meta.variant} className={cn(meta.pulsing && "animate-pulse")}>
          {meta.label}
        </Badge>
        {card.duration !== undefined && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            {card.duration.toFixed(2)}s
          </span>
        )}
      </div>
      {card.args && Object.keys(card.args).length > 0 && (
        <pre className="mt-2 max-h-36 overflow-auto rounded-md bg-secondary/50 p-2 font-mono text-[10px] leading-relaxed text-muted-foreground">
          {JSON.stringify(card.args, null, 2)}
        </pre>
      )}
      {card.summary && (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{card.summary}</p>
      )}
      {card.files && card.files.length > 0 && (
        <p className="mt-1.5 font-mono text-[10px] text-success">产出: {card.files.join(", ")}</p>
      )}
    </motion.div>
  );
}

export function ToolLog({ cards }: { cards: ToolCardData[] }) {
  if (cards.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-xs text-muted-foreground">
        Agent 的工具调用会实时显示在这里
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {cards.map((c) => (
        <ToolCard key={c.seq} card={c} />
      ))}
    </div>
  );
}
