"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check } from "lucide-react";
import { useCallStore } from "@/stores/callStore";

const FIELDS: { key: string; label: string }[] = [
  { key: "name", label: "Full name" },
  { key: "dob", label: "Date of birth" },
  { key: "phone", label: "Phone number" },
  { key: "symptoms", label: "Reason / symptoms" },
  { key: "insurance", label: "Insurance" },
];

export function IntakePanel() {
  const intake = useCallStore((s) => s.intake);
  const collected = FIELDS.filter((f) => intake[f.key]).length;
  const pct = Math.round((collected / FIELDS.length) * 100);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {collected} / {FIELDS.length} collected
        </span>
        <div className="h-1 w-24 overflow-hidden rounded-full bg-muted">
          <motion.div
            className="h-full rounded-full bg-primary"
            initial={false}
            animate={{ width: `${pct}%` }}
            transition={{ type: "spring", stiffness: 200, damping: 26 }}
          />
        </div>
      </div>

      <ul className="flex flex-col gap-2.5">
        {FIELDS.map((field) => {
          const value = intake[field.key];
          const done = Boolean(value);
          return (
            <li key={field.key} className="flex items-start gap-2.5">
              <span
                className={`mt-0.5 flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-full transition-colors ${
                  done
                    ? "bg-success/20 text-success"
                    : "border border-border bg-muted"
                }`}
              >
                <AnimatePresence>
                  {done && (
                    <motion.span
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ type: "spring", stiffness: 500, damping: 22 }}
                    >
                      <Check className="h-2.5 w-2.5" strokeWidth={3} />
                    </motion.span>
                  )}
                </AnimatePresence>
              </span>
              <div className="flex min-w-0 flex-col">
                <span className="text-[11px] text-muted-foreground">
                  {field.label}
                </span>
                <span
                  className={`truncate text-sm ${done ? "text-foreground" : "text-muted-foreground/40"}`}
                >
                  {value ?? "Waiting"}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
