import type { PlanStep } from "@/lib/types";
import { Badge } from "../ui/badge";

export function PlanPanel({
  plan,
  doneCount = 0,
  revisions = 0,
}: {
  plan: PlanStep[];
  /** 已完成的工具调用数（近似当前进度） */
  doneCount?: number;
  /** 计划被 update_plan 动态调整的次数 */
  revisions?: number;
}) {
  if (plan.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-xs text-muted-foreground">
        任务启动后这里显示步骤计划
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5 px-0.5 text-[11px] text-muted-foreground">
        <span>
          已完成 {Math.min(doneCount, plan.length)}/{plan.length} 步
        </span>
        {revisions > 0 && (
          <Badge variant="secondary" className="ml-auto text-[9px]">
            ⟳ 已调整 {revisions} 次
          </Badge>
        )}
      </div>
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
