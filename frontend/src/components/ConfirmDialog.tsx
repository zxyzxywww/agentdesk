import { AlertTriangle } from "lucide-react";
import { Button } from "./ui/button";
import { Dialog, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";
import type { PendingConfirm } from "@/lib/types";

export function ConfirmDialog({
  pending,
  onConfirm,
  onReject,
}: {
  pending: PendingConfirm | null;
  onConfirm: (callId: number) => void;
  onReject: (callId: number) => void;
}) {
  return (
    <Dialog open={!!pending} onOpenChange={() => {}}>
      {pending && (
        <>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="size-4" />
              危险操作需要你确认
            </DialogTitle>
            <DialogDescription>
              Agent 想执行 <code className="rounded bg-secondary px-1 font-mono text-xs">{pending.name}</code>，操作前需你确认：
            </DialogDescription>
          </DialogHeader>
          <pre className="max-h-56 overflow-auto rounded-lg bg-secondary/60 p-3 font-mono text-xs leading-relaxed">
            {JSON.stringify(pending.arguments, null, 2)}
          </pre>
          <DialogFooter>
            <Button variant="outline" onClick={() => onReject(pending.call_id)}>
              拒绝，换方案
            </Button>
            <Button variant="destructive" onClick={() => onConfirm(pending.call_id)}>
              确认执行
            </Button>
          </DialogFooter>
        </>
      )}
    </Dialog>
  );
}
