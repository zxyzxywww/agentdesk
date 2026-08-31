import type { ReactNode } from "react";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon,
  title,
  hint,
  className,
}: {
  icon: ReactNode;
  title: string;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "flex h-full flex-col items-center justify-center gap-2 p-8 text-center",
        className
      )}
    >
      <div className="flex size-12 items-center justify-center rounded-2xl bg-secondary text-2xl">
        {icon}
      </div>
      <div className="text-sm font-medium text-foreground">{title}</div>
      {hint && <div className="max-w-xs text-xs leading-relaxed text-muted-foreground">{hint}</div>}
    </motion.div>
  );
}
