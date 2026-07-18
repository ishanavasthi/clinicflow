"use client";

import type { LucideIcon } from "lucide-react";
import { Activity, BarChart3, History, Radio, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

export type ShellView = "call" | "history";

const NAV: {
  icon: LucideIcon;
  label: string;
  view?: ShellView;
}[] = [
  { icon: Radio, label: "Live call", view: "call" },
  { icon: History, label: "Call history", view: "history" },
  { icon: BarChart3, label: "Analytics" },
  { icon: Settings, label: "Settings" },
];

export function Sidebar({
  view,
  onSelect,
}: {
  view: ShellView;
  onSelect: (view: ShellView) => void;
}) {
  return (
    <aside className="hidden w-16 shrink-0 flex-col items-center gap-1 border-r border-border bg-sidebar/60 py-4 sm:flex">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/15 ring-1 ring-primary/25">
        <Activity className="h-5 w-5 text-primary" />
      </div>
      <nav className="flex flex-col items-center gap-1">
        {NAV.map(({ icon: Icon, label, view: itemView }) => {
          const active = itemView !== undefined && itemView === view;
          return (
            <button
              key={label}
              type="button"
              title={label}
              aria-label={label}
              aria-current={active ? "page" : undefined}
              onClick={itemView ? () => onSelect(itemView) : undefined}
              disabled={!itemView}
              className={cn(
                "group relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : itemView
                    ? "text-muted-foreground hover:bg-muted hover:text-foreground"
                    : "text-muted-foreground/40",
              )}
            >
              {active && (
                <span className="absolute left-0 h-5 w-0.5 -translate-x-2 rounded-full bg-primary" />
              )}
              <Icon className="h-[18px] w-[18px]" />
            </button>
          );
        })}
      </nav>
    </aside>
  );
}
