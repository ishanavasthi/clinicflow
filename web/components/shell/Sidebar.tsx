"use client";

import type { LucideIcon } from "lucide-react";
import { Activity, BarChart3, History, Radio, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV: { icon: LucideIcon; label: string; active?: boolean }[] = [
  { icon: Radio, label: "Live call", active: true },
  { icon: History, label: "Call history" },
  { icon: BarChart3, label: "Analytics" },
  { icon: Settings, label: "Settings" },
];

export function Sidebar() {
  return (
    <aside className="hidden w-16 shrink-0 flex-col items-center gap-1 border-r border-border bg-sidebar/60 py-4 sm:flex">
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/15 ring-1 ring-primary/25">
        <Activity className="h-5 w-5 text-primary" />
      </div>
      <nav className="flex flex-col items-center gap-1">
        {NAV.map(({ icon: Icon, label, active }) => (
          <button
            key={label}
            type="button"
            title={label}
            aria-label={label}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {active && (
              <span className="absolute left-0 h-5 w-0.5 -translate-x-2 rounded-full bg-primary" />
            )}
            <Icon className="h-[18px] w-[18px]" />
          </button>
        ))}
      </nav>
    </aside>
  );
}
