import type { CallStatus } from "@/lib/types";

const STATUS_LABEL: Record<CallStatus, string> = {
  idle: "Idle",
  ringing: "Ringing",
  connecting: "Connecting",
  active: "Active",
  "wrap-up": "Wrap-up",
  ended: "Ended",
  error: "Error",
};

export function StatusBadge({ status }: { status: CallStatus }) {
  const tone =
    status === "active"
      ? "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30"
      : status === "connecting"
        ? "bg-amber-500/15 text-amber-400 ring-amber-500/30"
        : status === "error"
          ? "bg-red-500/15 text-red-400 ring-red-500/30"
          : "bg-muted text-muted-foreground ring-border";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ${tone}`}
    >
      <span className="relative flex h-2 w-2">
        {status === "active" && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        )}
        <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}
