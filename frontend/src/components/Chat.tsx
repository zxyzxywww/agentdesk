import { useEffect, useRef } from "react";
import { Zap } from "lucide-react";
import { motion } from "motion/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import type { Message } from "@/lib/types";
import { EmptyState } from "./EmptyState";

function Bubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const kind = !isUser && message.content.startsWith("[反思]")
    ? "reflect"
    : !isUser && message.content.startsWith("[系统]")
      ? "system"
      : null;
  const body = kind
    ? message.content.replace(/^\[(反思|系统)\]\s*/, "")
    : message.content;
  const badge =
    kind === "reflect"
      ? { text: "反思自检", cls: "border-violet-500/40 bg-violet-500/10 text-violet-600" }
      : kind === "system"
        ? { text: "系统", cls: "border-slate-400/50 bg-slate-100 text-slate-500" }
        : null;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className={cn("flex", isUser ? "justify-end" : "justify-start")}
    >
      {isUser ? (
        <div className="max-w-[78%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground shadow-sm">
          {message.content}
        </div>
      ) : (
        <div
          className={cn(
            "max-w-[78%] rounded-2xl rounded-bl-md border bg-card px-4 py-2.5 text-sm leading-relaxed text-foreground shadow-sm",
            kind === "reflect" && "border-violet-500/30 bg-violet-500/[0.03]",
          )}
        >
          {badge && (
            <span
              className={cn(
                "mb-1.5 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide",
                badge.cls,
              )}
            >
              {kind === "reflect" ? "⟳" : "ⓘ"} {badge.text}
            </span>
          )}
          <div className="msg-md">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
          </div>
        </div>
      )}
    </motion.div>
  );
}

export function Chat({ messages }: { messages: Message[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4">
      {messages.length === 0 ? (
        <EmptyState
          icon={<Zap className="size-6 text-primary" />}
          title="给 AgentDesk 下达一个任务"
          hint={
            <>
              例如：<code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">把工作目录下所有 csv 合并为一个 all.csv</code>
              <br />
              或 <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-xs">调研一下 LLM agent 框架的现状</code>
            </>
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          {messages.map((m) => (
            <Bubble key={m.id} message={m} />
          ))}
        </div>
      )}
    </div>
  );
}
