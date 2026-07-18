"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Pencil, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { updatePatient } from "@/lib/api";
import { useCallStore } from "@/stores/callStore";

const FIELDS: { key: string; label: string; placeholder: string }[] = [
  { key: "name", label: "Full name", placeholder: "Full name" },
  { key: "age", label: "Age", placeholder: "e.g. 38" },
  { key: "phone", label: "Phone number", placeholder: "10-digit mobile" },
  { key: "symptoms", label: "Reason / symptoms", placeholder: "Reason for visit" },
];

export function IntakePanel() {
  const intake = useCallStore((s) => s.intake);
  const patientId = useCallStore((s) => s.patientId);
  const setIntakeFields = useCallStore((s) => s.setIntakeFields);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const collected = FIELDS.filter((f) => intake[f.key]).length;
  const pct = Math.round((collected / FIELDS.length) * 100);

  function startEdit() {
    setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, intake[f.key] ?? ""])));
    setEditing(true);
  }

  async function save() {
    // Only send fields that actually have a value.
    const changed = Object.fromEntries(
      Object.entries(draft).filter(([, v]) => v.trim() !== ""),
    );
    setIntakeFields(changed);
    setSaving(true);
    try {
      if (patientId != null) {
        await updatePatient(patientId, changed);
      }
      toast.success("Patient details updated");
      setEditing(false);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not save";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {collected} / {FIELDS.length} collected
        </span>
        <div className="flex items-center gap-2">
          {!editing && (
            <div className="h-1 w-20 overflow-hidden rounded-full bg-muted">
              <motion.div
                className="h-full rounded-full bg-primary"
                initial={false}
                animate={{ width: `${pct}%` }}
                transition={{ type: "spring", stiffness: 200, damping: 26 }}
              />
            </div>
          )}
          {!editing ? (
            <button
              type="button"
              onClick={startEdit}
              aria-label="Edit patient details"
              className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          ) : (
            <span className="eyebrow !text-[10px] text-primary">Editing</span>
          )}
        </div>
      </div>

      {editing ? (
        <div className="flex flex-col gap-3">
          {FIELDS.map((field) => (
            <label key={field.key} className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">{field.label}</span>
              <input
                value={draft[field.key] ?? ""}
                placeholder={field.placeholder}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, [field.key]: e.target.value }))
                }
                className="w-full rounded-md border border-border bg-elevated px-2.5 py-1.5 text-sm outline-none transition-colors placeholder:text-muted-foreground/40 focus:border-primary/50 focus:ring-1 focus:ring-primary/30"
              />
            </label>
          ))}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
              disabled={saving}
            >
              <X className="h-4 w-4" />
              Cancel
            </Button>
            <Button size="sm" onClick={save} disabled={saving}>
              <Check className="h-4 w-4" />
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      ) : (
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
      )}
    </div>
  );
}
