"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  CalendarCheck,
  ChevronRight,
  Mic,
  Split,
} from "lucide-react";
import { fetchCalls } from "@/lib/api";
import { fadeUp, stagger } from "@/lib/motion";
import type { CallListItem } from "@/lib/types";
import { CallDetail } from "@/components/history/CallDetail";

function outcomeChip(call: CallListItem) {
  if (call.summary.booking) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-xs text-success">
        <CalendarCheck className="h-3 w-3" /> Booked {call.summary.booking.doctor}
      </span>
    );
  }
  if (call.routed_department) {
    const emergency = call.routed_department === "Emergency";
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
          emergency
            ? "bg-emergency/15 text-emergency"
            : "bg-primary/10 text-primary"
        }`}
      >
        {emergency && <AlertTriangle className="h-3 w-3" />}
        <Split className="h-3 w-3" /> {call.routed_department}
      </span>
    );
  }
  return <span className="text-xs text-muted-foreground/60">No booking</span>;
}

export function HistoryView() {
  const [calls, setCalls] = useState<CallListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (selected !== null) return;
    fetchCalls()
      .then(setCalls)
      .catch((e: Error) => setError(e.message));
  }, [selected]);

  if (selected !== null) {
    return <CallDetail callId={selected} onBack={() => setSelected(null)} />;
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold tracking-tight">Call history</h2>
          <p className="text-xs text-muted-foreground">
            Past calls, most recent first.
          </p>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">
          {calls.length} call{calls.length === 1 ? "" : "s"}
        </span>
      </div>

      {error ? (
        <p className="rounded-lg border border-border bg-card/60 px-4 py-3 text-sm text-muted-foreground">
          Could not load history ({error}).
        </p>
      ) : calls.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border px-4 py-12 text-center text-sm text-muted-foreground">
          No calls yet. Place a call and it will appear here after it ends.
        </p>
      ) : (
        <motion.ul
          variants={stagger}
          initial="hidden"
          animate="show"
          className="flex flex-col gap-2"
        >
          {calls.map((call) => (
            <motion.li key={call.id} variants={fadeUp}>
              <button
                type="button"
                onClick={() => setSelected(call.id)}
                className="group flex w-full items-center gap-4 rounded-xl border border-border bg-card/60 px-4 py-3 text-left transition-colors hover:border-primary/30"
              >
                <div className="flex w-28 shrink-0 flex-col">
                  <span className="text-sm font-medium">
                    {call.summary.name ?? "Unknown"}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {new Date(call.started_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                    {call.summary.age ? ` · ${call.summary.age}` : ""}
                  </span>
                </div>
                <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                  {call.summary.symptom ?? "No reason recorded"}
                </span>
                {outcomeChip(call)}
                {call.recording_url && (
                  <Mic className="h-3.5 w-3.5 text-muted-foreground/60" />
                )}
                <ChevronRight className="h-4 w-4 text-muted-foreground/40 transition-colors group-hover:text-foreground" />
              </button>
            </motion.li>
          ))}
        </motion.ul>
      )}
    </div>
  );
}
