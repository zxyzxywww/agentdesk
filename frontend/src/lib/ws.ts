import { useEffect, useRef } from "react";
import type { AgentEvent } from "./types";

/**
 * 订阅任务的实时事件流（WebSocket）。
 * taskId 变化或组件卸载时自动断开；事件回调始终使用最新引用。
 */
export function useTaskSocket(
  taskId: string | null,
  onEvent: (e: AgentEvent) => void
) {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!taskId) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/tasks/${taskId}`);
    ws.onmessage = (ev) => {
      try {
        cbRef.current(JSON.parse(ev.data as string) as AgentEvent);
      } catch {
        /* 忽略坏帧 */
      }
    };
    return () => ws.close();
  }, [taskId]);
}
