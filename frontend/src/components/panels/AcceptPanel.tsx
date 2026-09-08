import { AlertCircle, CheckCircle2, ChevronRight, Coins, FileText, ListChecks, Timer, Wrench } from "lucide-react";
import { Badge } from "../ui/badge";
import { Td, THead, Table, TBody, Th, Tr } from "../ui/table";
import { fmtCost } from "@/lib/utils";
import type { TaskResult } from "@/lib/types";

const STATUS_BADGE: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  done: "success",
  stopped: "warning",
  failed: "destructive",
  waiting_confirm: "warning",
};

function PreviewTable({ result }: { result: Record<string, unknown> }) {
  const cols = (result.columns as string[]) ?? [];
  const rows = (result.preview as Record<string, unknown>[]) ?? [];
  if (!cols.length) return null;
  return (
    <Table className="mt-2">
      <THead>
        {cols.map((c) => (
          <Th key={c}>{c}</Th>
        ))}
      </THead>
      <TBody>
        {rows.map((row, i) => (
          <Tr key={i}>
            {cols.map((c) => (
              <Td key={c}>{String(row[c] ?? "")}</Td>
            ))}
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}

export function AcceptPanel({ result }: { result: TaskResult | null }) {
  if (!result) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-xs text-muted-foreground">
        任务结束后，这里展示验收结果
      </div>
    );
  }
  const badge = STATUS_BADGE[result.status] ?? "secondary";
  const done = result.status === "done";
  const icon = done ? (
    <CheckCircle2 className="size-5 text-success" />
  ) : result.status === "failed" ? (
    <AlertCircle className="size-5 text-destructive" />
  ) : (
    <Timer className="size-5 text-warning" />
  );

  return (
    <div className="flex flex-col gap-3.5">
      {/* 完成状态横幅 */}
      <div className="flex items-center gap-3 rounded-2xl bg-card px-4 py-3 ring-1 ring-border/60">
        {icon}
        <div className="min-w-0">
          <div className="text-sm font-semibold">
            {done ? "任务完成" : result.status === "failed" ? "任务失败" : "任务未完成"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {done ? "Agent 已交付最终结果，产出可点击查看" : `状态：${result.status}`}
          </div>
        </div>
        <Badge variant={badge} className="ml-auto shrink-0 uppercase">
          {result.status}
        </Badge>
      </div>

      {/* 指标：步数 / 成本 / 工具数 */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "步数", value: String(result.steps), icon: <Timer className="size-3.5" /> },
          { label: "成本", value: fmtCost(result.cost_yuan), icon: <Coins className="size-3.5" /> },
          { label: "工具调用", value: String(result.tool_calls.length), icon: <Wrench className="size-3.5" /> },
        ].map((m) => (
          <div key={m.label} className="flex flex-col gap-0.5 rounded-xl bg-card px-3 py-2.5 ring-1 ring-border/60">
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
              {m.icon}
              {m.label}
            </span>
            <span className="font-mono text-sm font-semibold text-foreground">{m.value}</span>
          </div>
        ))}
      </div>

      {result.summary && (
        <div className="rounded-2xl bg-card/60 px-4 py-3 text-sm leading-relaxed text-foreground">
          {result.summary}
        </div>
      )}

      {result.files.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <FileText className="size-3.5" />
            实际产出文件
          </div>
          <div className="flex flex-wrap gap-1.5">
            {result.files.map((f) => (
              <code
                key={f}
                className="rounded-lg bg-success/10 px-2 py-1 font-mono text-[11px] text-foreground ring-1 ring-success/20"
              >
                {f}
              </code>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <ListChecks className="size-3.5" />
          工具调用
        </div>
        {result.tool_calls.map((c, i) => (
          <details key={i} className="group mb-1.5 rounded-lg border bg-card">
            <summary className="flex cursor-pointer list-none items-center gap-2 p-2.5 text-xs [&::-webkit-details-marker]:hidden">
              <ChevronRight className="size-3.5 text-muted-foreground transition-transform group-open:rotate-90" />
              <code className="rounded bg-secondary px-1.5 py-0.5 font-mono">{c.name}</code>
              <Badge
                variant={
                  c.status === "success" ? "success" : c.status === "failed" ? "destructive" : "secondary"
                }
                className="text-[9px]"
              >
                {c.status}
              </Badge>
              <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                {c.duration_s.toFixed(2)}s
              </span>
            </summary>
            <div className="border-t p-2.5">
              {c.result?.preview ? (
                <PreviewTable result={c.result as Record<string, unknown>} />
              ) : (
                <pre className="max-h-48 overflow-auto font-mono text-[10px] leading-relaxed text-muted-foreground">
                  {JSON.stringify(c.result, null, 2).slice(0, 2000)}
                </pre>
              )}
              {c.result && (
                <div className="mt-2 flex items-center gap-1 text-[10px] text-success">
                  <CheckCircle2 className="size-3" />
                  已校验
                </div>
              )}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
