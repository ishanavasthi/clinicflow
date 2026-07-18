"use client";

import { RoomAudioRenderer } from "@livekit/components-react";
import { Card } from "@/components/ui/card";
import { useAgentState } from "@/hooks/useAgentState";
import { TranscriptFeed } from "@/components/transcript/TranscriptFeed";
import { IntakePanel } from "@/components/patient/IntakePanel";
import { AppointmentPanel } from "@/components/appointments/AppointmentPanel";
import { RoutingPanel } from "@/components/routing/RoutingPanel";
import { TimelinePanel } from "@/components/timeline/TimelinePanel";

/**
 * The live dashboard. Rendered inside a RoomContext, so the transcript hook and
 * the agent-state data channel are bound to the connected room. RoomAudioRenderer
 * plays the agent's voice through the browser speakers.
 */
export function CallWorkspace() {
  useAgentState();

  return (
    <div className="grid flex-1 gap-4 lg:grid-cols-3">
      <RoomAudioRenderer />

      {/* Column A: the call */}
      <Card className="flex max-h-[600px] flex-col overflow-hidden p-0 lg:col-span-1">
        <div className="border-b border-border px-4 py-3">
          <h3 className="text-sm font-medium">Live transcript</h3>
        </div>
        <TranscriptFeed />
      </Card>

      {/* Column B: the patient */}
      <div className="flex flex-col gap-4 lg:col-span-1">
        <Card className="p-4">
          <IntakePanel />
        </Card>
        <Card className="p-4">
          <AppointmentPanel />
        </Card>
      </div>

      {/* Column C: the operation */}
      <div className="flex flex-col gap-4 lg:col-span-1">
        <Card className="p-4">
          <RoutingPanel />
        </Card>
        <Card className="flex max-h-[320px] flex-col p-4">
          <TimelinePanel />
        </Card>
      </div>
    </div>
  );
}
