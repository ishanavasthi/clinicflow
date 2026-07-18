"use client";

import { useEffect, useRef } from "react";
import { useTranscriptions } from "@livekit/components-react";
import { useCallStore } from "@/stores/callStore";

/** Split a leading Muga tone tag like "[happy] " off the agent's text. */
function splitTone(text: string): { tone: string | null; body: string } {
  const match = text.match(/^\s*\[(\w+)\]\s*/);
  if (!match) return { tone: null, body: text };
  return { tone: match[1], body: text.slice(match[0].length) };
}

export function TranscriptFeed() {
  const transcriptions = useTranscriptions();
  const callerIdentity = useCallStore((s) => s.callerIdentity);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [transcriptions]);

  if (transcriptions.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-sm text-muted-foreground">
        The live transcript appears here once the caller and receptionist start
        talking.
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      {transcriptions.map((t, i) => {
        const isCaller = t.participantInfo.identity === callerIdentity;
        const { tone, body } = isCaller
          ? { tone: null, body: t.text }
          : splitTone(t.text);
        return (
          <div
            key={i}
            className={`flex flex-col gap-1 ${isCaller ? "items-end" : "items-start"}`}
          >
            <div className="flex items-center gap-2 px-1">
              <span className="text-xs font-medium text-muted-foreground">
                {isCaller ? "Caller" : "Riya"}
              </span>
              {tone && (
                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  {tone}
                </span>
              )}
            </div>
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                isCaller
                  ? "rounded-br-sm bg-primary text-primary-foreground"
                  : "rounded-bl-sm bg-muted text-foreground"
              }`}
            >
              {body || <span className="opacity-50">...</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
