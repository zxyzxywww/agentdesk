import type { PlanStep } from "@/lib/types";
import { Badge } from "../ui/badge";

export function PlanPanel({ plan }: { plan: PlanStep[] }) {
  if (plan.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-xs text-muted-foreground">
        任务启动后这里显示步骤计划
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      {plan.map((s, i) => (
        <div
          key={i}
          className="flex items-center gap-2.5 rounded-lg border bg-card px-3 py-2 text-sm"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 font-mono text-xs font-bold text-primary">
            {String(i + 1).padStart(2, "0")}
          </span>
          <span className="flex-1">{s.goal}</span>
          {s.tool && (
            <Badge variant="secondary" className="font-mono text-[10px]">
              {s.tool}
            </Badge>
          )}
        </div>
      ))}
    </div>
  );
}
