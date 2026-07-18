"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
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
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [transcriptions]);

  if (transcriptions.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <span className="flex h-2.5 w-2.5">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary/60" />
        </span>
        <p className="max-w-xs text-sm text-muted-foreground">
          Listening. The live transcript appears here as the caller and Riya
          start talking.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="flex h-full flex-col gap-3.5 overflow-y-auto scroll-thin p-4"
    >
      {transcriptions.map((t, i) => {
        const isCaller = t.participantInfo.identity === callerIdentity;
        const isLast = i === transcriptions.length - 1;
        const { tone, body } = isCaller
          ? { tone: null, body: t.text }
          : splitTone(t.text);
        return (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className={`flex flex-col gap-1 ${isCaller ? "items-end" : "items-start"}`}
          >
            <div className="flex items-center gap-2 px-1">
              <span className="eyebrow !text-[10px]">
                {isCaller ? "Caller" : "Riya"}
              </span>
              {tone && (
                <span className="rounded bg-primary/12 px-1.5 py-0.5 font-mono text-[10px] font-medium text-primary">
                  {tone}
                </span>
              )}
            </div>
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                isCaller
                  ? "rounded-br-sm bg-primary text-primary-foreground"
                  : "rounded-bl-sm border border-border bg-elevated text-foreground"
              }`}
            >
              {body || <span className="opacity-50">...</span>}
              {isLast && !isCaller && (
                <span className="ml-0.5 inline-block h-3.5 w-[2px] translate-y-0.5 animate-pulse bg-primary" />
              )}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
