"use client";

import { Download, Mic } from "lucide-react";
import { useCallStore } from "@/stores/callStore";

export function RecordingPlayer() {
  const recordingUrl = useCallStore((s) => s.recordingUrl);

  if (!recordingUrl) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-6 text-center">
        <Mic className="h-5 w-5 text-muted-foreground/50" />
        <p className="text-xs text-muted-foreground">
          No recording was captured for this call.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <audio
        controls
        src={recordingUrl}
        className="w-full"
        style={{ colorScheme: "dark" }}
      />
      <a
        href={recordingUrl}
        download="clinicflow-call.wav"
        className="inline-flex w-fit items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <Download className="h-3.5 w-3.5" />
        Download recording
      </a>
    </div>
  );
}
