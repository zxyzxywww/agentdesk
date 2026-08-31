import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import { ToolLog, type ToolCardData } from "./panels/ToolLog";
import { PlanPanel } from "./panels/PlanPanel";
import { FilePanel } from "./panels/FilePanel";
import { AcceptPanel } from "./panels/AcceptPanel";
import { UndoPanel } from "./panels/UndoPanel";
import type {
  BackupRecord,
  PlanStep,
  TaskResult,
  WorkspaceEntry,
} from "@/lib/types";

export const PANEL_TABS = ["run", "plan", "files", "accept", "undo"] as const;
export type PanelTab = (typeof PANEL_TABS)[number];

export function RightPanel({
  tab,
  onTabChange,
  toolCards,
  plan,
  files,
  accept,
  backups,
  onRestore,
}: {
  tab: PanelTab;
  onTabChange: (t: PanelTab) => void;
  toolCards: ToolCardData[];
  plan: PlanStep[];
  files: WorkspaceEntry[];
  accept: TaskResult | null;
  backups: BackupRecord[];
  onRestore: (id: number) => void;
}) {
  const labels: Record<PanelTab, string> = {
    run: "执行",
    plan: "计划",
    files: "文件",
    accept: "验收",
    undo: "撤销",
  };

  return (
    <aside className="flex h-full w-full shrink-0 flex-col border-l bg-card/40">
      <div className="px-3 pt-3">
        <Tabs value={tab} onValueChange={(v) => onTabChange(v as PanelTab)}>
          <TabsList>
            {PANEL_TABS.map((t) => (
              <TabsTrigger key={t} value={t}>
                {labels[t]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>
      <div className="mt-1 flex-1 overflow-y-auto px-3 pb-3">
        <Tabs value={tab} onValueChange={(v) => onTabChange(v as PanelTab)}>
          <TabsContent value="run">
            <ToolLog cards={toolCards} />
          </TabsContent>
          <TabsContent value="plan">
            <PlanPanel plan={plan} />
          </TabsContent>
          <TabsContent value="files">
            <FilePanel files={files} />
          </TabsContent>
          <TabsContent value="accept">
            <AcceptPanel result={accept} />
          </TabsContent>
          <TabsContent value="undo">
            <UndoPanel backups={backups} onRestore={onRestore} />
          </TabsContent>
        </Tabs>
      </div>
    </aside>
  );
}
