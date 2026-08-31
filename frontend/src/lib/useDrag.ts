import { useRef } from "react";

/**
 * 通用拖拽手势（Pointer Events），返回 onPointerDown。
 * - axis: "x" | "y"，拖拽方向
 * - onDelta: 每次移动的增量（px），由调用方决定如何应用到目标尺寸
 * 拖动期间禁用文字选中，结束后恢复。基于事件监听，贴合现有布局、不引入重依赖。
 */
export function useDrag(
  axis: "x" | "y",
  onDelta: (delta: number) => void
) {
  const start = useRef(0);
  const active = useRef(false);

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    active.current = true;
    start.current = axis === "x" ? e.clientX : e.clientY;
    document.body.style.userSelect = "none";
    document.body.style.cursor = axis === "x" ? "col-resize" : "row-resize";

    const move = (ev: PointerEvent) => {
      if (!active.current) return;
      const cur = axis === "x" ? ev.clientX : ev.clientY;
      const d = cur - start.current;
      if (d !== 0) {
        onDelta(d);
        start.current = cur;
      }
    };
    const up = () => {
      active.current = false;
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  };

  return onPointerDown;
}
