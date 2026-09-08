import { Check, CircleDashed } from "lucide-react";
import type { PlanStep } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PlanPanel({
  plan,
  doneCount,
  revisions,
}: {
  plan: PlanStep[];
  /** 已执行完成的工具调用数（近似当前进度） */
  doneCount?: number;
  /** 计划被动态调整的次数（update_plan） */
  revisions?: number;
}) {
  if (plan.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-xs text-muted-foreground">
        任务启动后这里显示步骤计划
      </div>
    );
  }
  const executed = doneCount ?? 0;
  return (
    <div className="flex flex-col">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
          执行计划
        </span>
        {(revisions ?? 0) > 0 && (
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
            ⟳ 已调整 {revisions} 次
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {executed}/{plan.length} 步
        </span>
      </div>
      <div className="relative space-y-1 pl-4">
        {/* 时间线 */}
        <span className="absolute left-[7px] top-2 bottom-2 w-px bg-border" aria-hidden />
        {plan.map((s, i) => {
          const isDone = i < executed;
          const isCurrent = !isDone && i <= executed;
          const waiting = !isDone && !isCurrent;
          return (
            <div
              key={i}
              className={cn(
                "relative flex items-start gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors",
                isCurrent
                  ? "bg-primary/[0.05] ring-1 ring-primary/20"
                  : "hover:bg-secondary/50",
              )}
            >
              <span
                className={cn(
                  "absolute -left-4 top-1/2 flex size-3.5 -translate-y-1/2 items-center justify-center rounded-full",
                  isDone
                    ? "bg-success text-white"
                    : isCurrent
                      ? "bg-primary text-white ring-4 ring-primary/15"
                      : "border bg-background",
                )}
                style={isCurrent ? undefined : { marginLeft: 0 }}
                aria-hidden
              >
                {isDone && <Check className="size-2.5" />}
                {isCurrent && !isDone && <span className="size-1.5 animate-pulse rounded-full bg-white" />}
              </span>
              <div className="min-w-0">
                <p
                  className={cn(
                    "leading-snug",
                    isDone && "text-muted-foreground line-through decoration-muted-foreground/40",
                    waiting && "text-muted-foreground/70",
                    isCurrent && "font-medium text-foreground",
                  )}
                >
                  {s.goal}
                </p>
                {s.tool && (
                  <code className="mt-0.5 inline-block font-mono text-[10px] text-muted-foreground/80">
                    {s.tool}
                  </code>
                )}
              </div>
              {waiting && <CircleDashed className="ml-auto size-3.5 shrink-0 text-muted-foreground/40" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
