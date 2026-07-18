"use client";

import { AlertTriangle } from "lucide-react";
import { useCallStore } from "@/stores/callStore";

const DEPARTMENTS = [
  "Emergency",
  "General Medicine",
  "Pediatrics",
  "Orthopedics",
  "Cardiology",
];

export function RoutingPanel() {
  const routing = useCallStore((s) => s.routing);
  const active = routing?.department ?? null;
  const emergency = routing?.emergency ?? false;

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-sm font-medium">Department routing</h3>

      <div className="flex flex-wrap gap-2">
        {DEPARTMENTS.map((dept) => {
          const isActive = dept === active;
          const isEmergency = isActive && emergency;
          return (
            <span
              key={dept}
              className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 transition-colors ${
                isEmergency
                  ? "bg-red-500/20 text-red-400 ring-red-500/40"
                  : isActive
                    ? "bg-primary/15 text-primary ring-primary/40"
                    : "bg-muted text-muted-foreground ring-border"
              }`}
            >
              {isEmergency && <AlertTriangle className="h-3 w-3" />}
              {dept}
            </span>
          );
        })}
      </div>

      {routing ? (
        <p
          className={`text-xs ${emergency ? "text-red-400" : "text-muted-foreground"}`}
        >
          {emergency ? "Emergency routing: " : "Routed: "}
          {routing.reason}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground/60">
          The caller has not been routed yet.
        </p>
      )}
    </div>
  );
}
