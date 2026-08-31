import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface SelectContextValue {
  value: string;
  onValueChange: (v: string) => void;
  open: boolean;
  setOpen: (o: boolean) => void;
}
const SelectContext = React.createContext<SelectContextValue | null>(null);

export function Select({
  value,
  onValueChange,
  children,
  className,
}: {
  value: string;
  onValueChange: (v: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <SelectContext.Provider value={{ value, onValueChange, open, setOpen }}>
      <div className={cn("relative", className)}>{children}</div>
    </SelectContext.Provider>
  );
}

export function SelectTrigger({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ctx = React.useContext(SelectContext)!;
  return (
    <button
      onClick={() => ctx.setOpen(!ctx.open)}
      className={cn(
        "flex h-8 w-full items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-xs shadow-sm transition-colors hover:bg-secondary/50 cursor-pointer",
        className
      )}
    >
      {children}
      <ChevronDown className="size-3.5 text-muted-foreground" />
    </button>
  );
}

export function SelectValue({ placeholder }: { placeholder?: string }) {
  const ctx = React.useContext(SelectContext)!;
  return <span className="truncate">{ctx.value || placeholder}</span>;
}

export function SelectContent({ children }: { children: React.ReactNode }) {
  const ctx = React.useContext(SelectContext)!;
  if (!ctx.open) return null;
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={() => ctx.setOpen(false)} />
      <div className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-md border bg-popover p-1 shadow-lg animate-[zoomIn_.12s_ease]">
        {children}
      </div>
    </>
  );
}

export function SelectItem({
  value,
  children,
}: {
  value: string;
  children: React.ReactNode;
}) {
  const ctx = React.useContext(SelectContext)!;
  return (
    <button
      onClick={() => {
        ctx.onValueChange(value);
        ctx.setOpen(false);
      }}
      className={cn(
        "flex w-full items-center rounded-sm px-2 py-1.5 text-left text-xs transition-colors cursor-pointer",
        ctx.value === value ? "bg-primary/10 text-primary font-medium" : "hover:bg-secondary"
      )}
    >
      {children}
    </button>
  );
}
