"use client";

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

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Patient intake</h3>
        <span className="text-xs text-muted-foreground">
          {collected}/{FIELDS.length}
        </span>
      </div>
      <ul className="flex flex-col gap-2">
        {FIELDS.map((field) => {
          const value = intake[field.key];
          const done = Boolean(value);
          return (
            <li key={field.key} className="flex items-start gap-2.5">
              <span
                className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
                  done
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "border border-border bg-muted"
                }`}
              >
                {done && <Check className="h-2.5 w-2.5" />}
              </span>
              <div className="flex min-w-0 flex-col">
                <span className="text-xs text-muted-foreground">{field.label}</span>
                <span
                  className={`truncate text-sm ${done ? "text-foreground" : "text-muted-foreground/50"}`}
                >
                  {value ?? "Waiting..."}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
