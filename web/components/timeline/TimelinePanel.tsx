"use client";

import { useCallStore } from "@/stores/callStore";

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function TimelinePanel() {
  const timeline = useCallStore((s) => s.timeline);

  return (
    <div className="flex h-full flex-col gap-3">
      <h3 className="text-sm font-medium">Conversation timeline</h3>

      {timeline.length === 0 ? (
        <p className="text-xs text-muted-foreground/60">
          Tool calls and phase changes appear here as they happen.
        </p>
      ) : (
        <ol className="flex flex-col gap-0 overflow-y-auto">
          {timeline.map((entry) => (
            <li key={entry.id} className="flex gap-3 pb-3 last:pb-0">
              <div className="flex flex-col items-center">
                <span
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                    entry.emphasis === "success"
                      ? "bg-emerald-400"
                      : entry.emphasis === "alert"
                        ? "bg-red-400"
                        : "bg-muted-foreground/50"
                  }`}
                />
                <span className="w-px flex-1 bg-border" />
              </div>
              <div className="flex flex-col pb-1">
                <span className="text-sm">{entry.label}</span>
                <span className="text-[10px] text-muted-foreground">
                  {formatTime(entry.ts)}
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
