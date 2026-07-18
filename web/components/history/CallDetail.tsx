"use client";

import { useEffect, useState } from "react";
import {
  ArrowLeft,
  CalendarCheck,
  Download,
  MessagesSquare,
  Split,
  UserRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/Panel";
import { fetchCall, mediaUrl } from "@/lib/api";
import type { CallDetailData } from "@/lib/types";

function outcome(call: CallDetailData): string {
  if (call.summary.booking) return `Booked ${call.summary.booking.doctor}`;
  if (call.routed_department) return `Routed to ${call.routed_department}`;
  return "No booking";
}

export function CallDetail({
  callId,
  onBack,
}: {
  callId: number;
  onBack: () => void;
}) {
  const [call, setCall] = useState<CallDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCall(callId)
      .then(setCall)
      .catch((e: Error) => setError(e.message));
  }, [callId]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        {call && (
          <span className="font-mono text-xs text-muted-foreground">
            {call.summary.name ?? "Unknown caller"} &middot;{" "}
            {new Date(call.started_at).toLocaleString()}
          </span>
        )}
      </div>

      {error ? (
        <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </p>
      ) : !call ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-12">
          {/* Transcript */}
          <Panel
            label="Transcript"
            icon={<MessagesSquare className="h-3.5 w-3.5" />}
            className="max-h-[560px] lg:col-span-7"
            scroll
          >
            {call.transcript.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No transcript was captured.
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                {call.transcript.map((m, i) => {
                  const isCaller = m.role === "user";
                  return (
                    <div
                      key={i}
                      className={`flex flex-col gap-1 ${isCaller ? "items-end" : "items-start"}`}
                    >
                      <span className="eyebrow !text-[10px]">
                        {isCaller ? "Caller" : "Riya"}
                      </span>
                      <div
                        className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                          isCaller
                            ? "rounded-br-sm bg-primary text-primary-foreground"
                            : "rounded-bl-sm border border-border bg-elevated"
                        }`}
                      >
                        {m.text}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>

          {/* Patient + outcome + recording */}
          <div className="flex flex-col gap-4 lg:col-span-5">
            <Panel label="Patient" icon={<UserRound className="h-3.5 w-3.5" />}>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Name</dt>
                <dd>{call.summary.name ?? "Not captured"}</dd>
                <dt className="text-muted-foreground">Age</dt>
                <dd>{call.summary.age ?? "-"}</dd>
                <dt className="text-muted-foreground">Phone</dt>
                <dd className="font-mono text-xs">{call.summary.phone ?? "-"}</dd>
                <dt className="text-muted-foreground">Symptom</dt>
                <dd>{call.summary.symptom ?? "-"}</dd>
              </dl>
            </Panel>

            <Panel label="Outcome" icon={<Split className="h-3.5 w-3.5" />}>
              {call.summary.booking ? (
                <div className="flex flex-col gap-1 rounded-lg border border-success/30 bg-success/10 p-3 text-sm">
                  <span className="flex items-center gap-1.5 text-success">
                    <CalendarCheck className="h-4 w-4" /> Booked
                  </span>
                  <span>{call.summary.booking.doctor}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {call.summary.booking.department} &middot;{" "}
                    {call.summary.booking.when}
                  </span>
                </div>
              ) : (
                <p className="text-sm">{outcome(call)}</p>
              )}
            </Panel>

            {call.recording_url && (
              <Panel label="Recording" icon={<Download className="h-3.5 w-3.5" />}>
                <audio
                  controls
                  src={mediaUrl(call.recording_url)}
                  className="w-full"
                  style={{ colorScheme: "dark" }}
                />
              </Panel>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
