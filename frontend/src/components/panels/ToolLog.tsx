import { motion } from "motion/react";
import { ChevronRight } from "lucide-react";
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
  const dotColor =
    card.status === "start"
      ? "var(--color-primary)"
      : card.status === "success"
        ? "var(--color-success)"
        : card.status === "failed"
          ? "var(--color-destructive)"
          : "var(--color-warning)";
  const argsEntries = Object.entries(card.args ?? {});
  // 简要参数：取前两个关键参数拼成一行（防长 JSON 撑爆卡片）
  const brief = argsEntries
    .slice(0, 2)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("  ·  ");
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15 }}
      className="relative pl-5"
    >
      {/* 时间线：竖线 + 状态圆点 */}
      <span
        className="absolute left-[5px] top-0 h-full w-px bg-border"
        aria-hidden
      />
      <span
        className={cn(
          "absolute left-0 top-[15px] size-[11px] -translate-x-1/2 rounded-full ring-4 ring-background",
          card.status === "start" && "animate-pulse",
        )}
        style={{ background: dotColor }}
        aria-hidden
      />
      <div className="rounded-xl bg-card px-3 py-2.5 ring-1 ring-border/60 transition-shadow hover:ring-border">
        <div className="flex items-center gap-2">
          <code className="truncate font-mono text-xs font-semibold text-foreground">
            {card.name}
          </code>
          <Badge variant={meta.variant} className={cn("shrink-0", meta.pulsing && "animate-pulse")}>
            {meta.label}
          </Badge>
          {card.duration !== undefined && (
            <span className="ml-auto shrink-0 font-mono text-[10px] text-muted-foreground">
              {card.duration.toFixed(2)}s
            </span>
          )}
        </div>
        {brief && (
          <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground" title={brief}>
            {brief}
          </p>
        )}
        {card.summary && (
          <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
            {card.summary}
          </p>
        )}
        {argsEntries.length > 0 && (
          <details className="group mt-1.5">
            <summary className="flex cursor-pointer list-none items-center gap-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3 transition-transform group-open:rotate-90" />
              查看完整参数与结果
            </summary>
            <pre className="mt-1.5 max-h-44 overflow-auto rounded-lg bg-secondary/60 p-2.5 font-mono text-[10px] leading-relaxed break-all whitespace-pre-wrap">
              {JSON.stringify(card.args, null, 2)}
            </pre>
          </details>
        )}
        {card.files && card.files.length > 0 && (
          <p className="mt-1.5 truncate font-mono text-[10px] text-success" title={card.files.join(", ")}>
            产出: {card.files.join(", ")}
          </p>
        )}
      </div>
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
