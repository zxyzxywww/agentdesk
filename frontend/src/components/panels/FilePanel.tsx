import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, File as FileIcon, Folder, Upload } from "lucide-react";
import { toast } from "sonner";
import { cn, fmtSize } from "@/lib/utils";
import { api } from "@/lib/api";
import type { WorkspaceEntry } from "@/lib/types";

/**
 * 工作目录文件浏览器：自管加载，支持点击文件夹进入子目录、返回上一层。
 * refreshKey 变化时（任务完成/切换会话）重载当前路径。
 */
export function FilePanel({ refreshKey }: { refreshKey: number }) {
  const [path, setPath] = useState(".");
  const [entries, setEntries] = useState<WorkspaceEntry[]>([]);
  const [hist, setHist] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async (p: string) => {
    setLoading(true);
    try {
      const r = await api.workspace.files(p);
      setEntries(r.entries ?? []);
    } catch (e) {
      toast.error("加载目录失败：" + (e as Error).message);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(path);
  }, [load, path, refreshKey]);

  const enterDir = (name: string) => {
    setHist((h) => [...h, path]);
    setPath(path === "." ? name : `${path}/${name}`);
  };

  const goBack = () => {
    setHist((h) => {
      if (!h.length) return h;
      setPath(h[h.length - 1]);
      return h.slice(0, -1);
    });
  };

  const uploadFiles = useCallback(
    async (list: FileList | File[]) => {
      for (const f of Array.from(list)) {
        try {
          await api.workspace.upload(f);
          toast.success(`已上传 ${f.name}`);
        } catch (e) {
          toast.error(`上传 ${f.name} 失败: ${(e as Error).message}`);
        }
      }
      load(path);
    },
    [load, path]
  );

  return (
    <div className="flex h-full flex-col gap-2.5">
      {/* 当前路径 + 返回 */}
      <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
        {hist.length > 0 && (
          <button
            onClick={goBack}
            className="flex shrink-0 items-center gap-0.5 rounded px-1 py-0.5 transition-colors hover:bg-secondary hover:text-foreground"
            title="返回上一层"
          >
            <ChevronLeft className="size-3.5" />
            返回
          </button>
        )}
        <code className="truncate font-mono">{path}</code>
      </div>

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
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-5 text-center text-xs transition-colors",
          dragging
            ? "border-primary bg-primary/5 text-primary"
            : "border-border text-muted-foreground hover:border-primary/50 hover:text-primary"
        )}
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
        {loading ? (
          <div className="py-10 text-center text-xs text-muted-foreground">加载中…</div>
        ) : entries.length === 0 ? (
          <div className="py-10 text-center text-xs text-muted-foreground">
            此目录为空
            <br />
            拖拽文件上来，或让 Agent 去创建
          </div>
        ) : (
          entries.map((f) => (
            <div
              key={f.name}
              data-entry={f.type}
              onClick={() => f.type === "dir" && enterDir(f.name)}
              className={cn(
                "group flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-xs transition-colors",
                f.type === "dir"
                  ? "cursor-pointer hover:bg-secondary/60"
                  : "hover:bg-secondary/40"
              )}
            >
              {f.type === "dir" ? (
                <Folder className="size-3.5 shrink-0 text-muted-foreground" />
              ) : (
                <FileIcon className="size-3.5 shrink-0 text-muted-foreground" />
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
