import { useState } from "react";
import { Play, Square } from "lucide-react";
import { Button } from "./ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Textarea } from "./ui/textarea";
const TEMPLATES: { value: string; label: string }[] = [
  { value: "列出工作目录下的所有文件，并概括一下有什么", label: "列出工作目录下的所有文件" },
  { value: "把工作目录下所有 csv 文件合并为一个 all.csv", label: "合并所有 csv" },
  { value: "把工作目录里的文件按类型归档到子文件夹", label: "按类型归档文件" },
  { value: "调研一下 LLM agent 框架的现状，写一份带引用来源的调研笔记", label: "网页调研：LLM agent 框架现状" },
  {
    value:
      "请调研「医学影像 AI 去噪」方向的技术现状与临床落地趋势：先用 web_search 查至少 3 个不同来源，再逐篇 fetch 关键页面核实，最后把结论写成一份带小标题、要点和引用来源的调研报告 report.md（先查资料再动笔，完成后自查是否覆盖了：主流方法、代表论文/产品、临床落地情况三个要点）",
    label: "业务调研：医影去噪技术现状报告(.md)",
  },
];

export function Composer({
  running,
  height,
  onResizeStart,
  onSend,
  onStop,
}: {
  running: boolean;
  height: number;
  onResizeStart: (e: React.PointerEvent) => void;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const [template, setTemplate] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || running) return;
    setText("");
    onSend(t);
  };

  return (
    <div className="relative shrink-0 border-t bg-card/60" style={{ height }}>
      {/* 上边界拖拽手柄 */}
      <div
        onPointerDown={onResizeStart}
        data-resize="bottom"
        className="absolute -top-1.5 left-0 right-0 h-1.5 cursor-row-resize transition-colors hover:bg-primary/40"
        title="拖拽调整输入区高度"
      />
      <div className="flex h-full flex-col p-3.5">
        <div className="mb-2.5 flex items-center gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
            快捷模板
          </span>
          <Select value={template} onValueChange={(v) => { setTemplate(v); setText(v); }}>
            <SelectTrigger className="h-7 w-48 text-xs">
              <SelectValue placeholder="选择一个试试…" />
            </SelectTrigger>
            <SelectContent>
              {TEMPLATES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="ml-auto hidden whitespace-nowrap text-[11px] text-muted-foreground/80 sm:block">
            危险操作先确认 · 覆盖前自动备份可撤销
          </span>
          {running && (
            <Button size="sm" variant="destructive" onClick={onStop}>
              <Square className="size-3.5" />
              停止
            </Button>
          )}
        </div>

        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="min-h-0 flex-1 resize-none text-[15px] leading-relaxed"
          placeholder="下达任务，例如：把工作目录下所有 csv 合并为一个 all.csv · Enter 发送，Shift+Enter 换行"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />

        <div className="mt-2.5 flex items-center justify-end gap-2">
          {!running && text.trim() && (
            <span className="mr-auto text-[11px] text-muted-foreground">
              将交给 Agent 自主规划与执行
            </span>
          )}
          <Button onClick={submit} disabled={running || !text.trim()} className="h-9 px-5 shadow-sm">
            <Play className="size-4" />
            运行任务
          </Button>
        </div>
      </div>
    </div>
  );
}
