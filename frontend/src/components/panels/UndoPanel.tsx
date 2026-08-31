import { RotateCcw, ShieldCheck } from "lucide-react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import type { BackupRecord } from "@/lib/types";

export function UndoPanel({
  backups,
  onRestore,
}: {
  backups: BackupRecord[];
  onRestore: (id: number) => void;
}) {
  if (backups.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <div className="flex size-11 items-center justify-center rounded-2xl bg-secondary">
          <ShieldCheck className="size-5 text-muted-foreground" />
        </div>
        <div className="text-xs font-medium">暂无备份</div>
        <div className="max-w-[220px] text-[11px] leading-relaxed text-muted-foreground">
          Agent 覆盖或删除文件前会自动备份，这里可一键恢复
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      {backups.map((b) => (
        <div key={b.id} className="flex items-center gap-2 rounded-lg border bg-card px-2.5 py-2 text-xs">
          <code className="truncate font-mono">{b.src_rel}</code>
          <span className="shrink-0 text-[10px] text-muted-foreground">{b.op}</span>
          {b.restored ? (
            <Badge variant="success" className="ml-auto text-[9px]">
              已恢复
            </Badge>
          ) : (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto h-6 px-2 text-[10px]"
              onClick={() => onRestore(b.id)}
            >
              <RotateCcw className="size-3" />
              恢复
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
