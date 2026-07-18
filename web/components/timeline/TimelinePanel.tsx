"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  CalendarCheck,
  HelpCircle,
  PhoneOff,
  Split,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import type { AgentStateEvent } from "@/lib/types";
import { useCallStore, type TimelineEntry } from "@/stores/callStore";

const ICON: Record<AgentStateEvent["type"], LucideIcon> = {
  status: PhoneOff,
  intake_update: UserPlus,
  booking: CalendarCheck,
  routing: Split,
  faq: HelpCircle,
  timeline: HelpCircle,
};

function dotColor(entry: TimelineEntry): string {
  if (entry.emphasis === "success") return "bg-success/15 text-success";
  if (entry.emphasis === "alert") return "bg-emergency/15 text-emergency";
  return "bg-muted text-muted-foreground";
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function TimelinePanel() {
  const timeline = useCallStore((s) => s.timeline);

  if (timeline.length === 0) {
    return (
      <p className="text-xs text-muted-foreground/60">
        Tool calls and phase changes log here as they happen.
      </p>
    );
  }

  return (
    <ol className="flex flex-col">
      <AnimatePresence initial={false}>
        {timeline.map((entry, i) => {
          const Icon = ICON[entry.type] ?? HelpCircle;
          const last = i === timeline.length - 1;
          return (
            <motion.li
              key={entry.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.25 }}
              className="flex gap-3"
            >
              <div className="flex flex-col items-center">
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${dotColor(entry)}`}
                >
                  <Icon className="h-2.5 w-2.5" />
                </span>
                {!last && <span className="w-px flex-1 bg-border" />}
              </div>
              <div className="flex flex-col pb-3">
                <span className="text-sm leading-tight">{entry.label}</span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {formatTime(entry.ts)}
                </span>
              </div>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
