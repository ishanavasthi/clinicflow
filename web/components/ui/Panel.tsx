"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { fadeUp } from "@/lib/motion";

interface PanelProps {
  label: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  scroll?: boolean;
}

/** A titled console panel: a mono eyebrow header over a bordered surface. */
export function Panel({
  label,
  icon,
  action,
  children,
  className,
  bodyClassName,
  scroll,
}: PanelProps) {
  return (
    <motion.section
      variants={fadeUp}
      className={cn(
        "flex min-h-0 flex-col rounded-xl border border-border bg-card/70 backdrop-blur-sm",
        className,
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b border-border/60 px-4 py-2.5">
        <div className="flex items-center gap-2 text-muted-foreground">
          {icon}
          <span className="eyebrow">{label}</span>
        </div>
        {action}
      </header>
      <div
        className={cn(
          "min-h-0 flex-1 p-4",
          scroll && "overflow-y-auto scroll-thin",
          bodyClassName,
        )}
      >
        {children}
      </div>
    </motion.section>
  );
}
