import { useCallback, useRef, useState } from "react";
import { File as FileIcon, Folder, Upload } from "lucide-react";
import { toast } from "sonner";
import { fmtSize } from "@/lib/utils";
import { api } from "@/lib/api";
import type { WorkspaceEntry } from "@/lib/types";

export function FilePanel({ files }: { files: WorkspaceEntry[] }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(async (list: FileList | File[]) => {
    for (const f of Array.from(list)) {
      try {
        await api.workspace.upload(f);
        toast.success(`已上传 ${f.name}`);
      } catch (e) {
        toast.error(`上传 ${f.name} 失败: ${(e as Error).message}`);
      }
    }
  }, []);

  return (
    <div className="flex h-full flex-col gap-2.5">
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          uploadFiles(e.dataTransfer.files);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-5 text-center text-xs transition-colors ${
          dragging
            ? "border-primary bg-primary/5 text-primary"
            : "border-border text-muted-foreground hover:border-primary/50 hover:text-primary"
        }`}
      >
        <Upload className="size-4" />
        拖拽文件到此处上传，或点击选择
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) uploadFiles(e.target.files);
          e.target.value = "";
        }}
      />

      <div className="flex-1 space-y-1 overflow-y-auto">
        {files.length === 0 ? (
          <div className="py-10 text-center text-xs text-muted-foreground">
            工作目录是空的
            <br />
            拖拽文件上来，或让 Agent 去创建
          </div>
        ) : (
          files.map((f) => (
            <div
              key={f.name}
              className="group flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-xs transition-colors hover:bg-secondary/50"
            >
              {f.type === "dir" ? (
                <Folder className="size-3.5 text-muted-foreground" />
              ) : (
                <FileIcon className="size-3.5 text-muted-foreground" />
              )}
              <span className="truncate font-mono">{f.name}</span>
              <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                {f.type === "file" ? fmtSize(f.size) : ""}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
