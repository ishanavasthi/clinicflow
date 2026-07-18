"use client";

import { motion } from "framer-motion";
import { RoomAudioRenderer } from "@livekit/components-react";
import {
  CalendarClock,
  ListTree,
  MessagesSquare,
  Split,
  UserRound,
} from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { stagger } from "@/lib/motion";
import { useAgentState } from "@/hooks/useAgentState";
import { AgentAudioVisualizer } from "@/components/call/AudioVisualizer";
import { CallTimer } from "@/components/call/CallTimer";
import { TranscriptFeed } from "@/components/transcript/TranscriptFeed";
import { IntakePanel } from "@/components/patient/IntakePanel";
import { AppointmentPanel } from "@/components/appointments/AppointmentPanel";
import { DepartmentFlow } from "@/components/routing/DepartmentFlow";
import { TimelinePanel } from "@/components/timeline/TimelinePanel";

/**
 * The live dashboard. Rendered inside a RoomContext, so the transcript hook and
 * the agent-state data channel are bound to the connected room. RoomAudioRenderer
 * plays the agent's voice through the browser speakers.
 */
export function CallWorkspace() {
  useAgentState();

  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="grid flex-1 gap-4 lg:grid-cols-12"
    >
      <RoomAudioRenderer />

      {/* Column A: the call */}
      <Panel
        label="Live call"
        icon={<MessagesSquare className="h-3.5 w-3.5" />}
        className="lg:col-span-5"
        bodyClassName="p-0"
        action={
          <div className="flex items-center gap-3">
            <AgentAudioVisualizer />
            <CallTimer />
          </div>
        }
      >
        <div className="h-[560px]">
          <TranscriptFeed />
        </div>
      </Panel>

      {/* Column B: the patient */}
      <div className="flex flex-col gap-4 lg:col-span-4">
        <Panel label="Patient intake" icon={<UserRound className="h-3.5 w-3.5" />}>
          <IntakePanel />
        </Panel>
        <Panel
          label="Appointment"
          icon={<CalendarClock className="h-3.5 w-3.5" />}
        >
          <AppointmentPanel />
        </Panel>
      </div>

      {/* Column C: the operation */}
      <div className="flex flex-col gap-4 lg:col-span-3">
        <Panel label="Routing" icon={<Split className="h-3.5 w-3.5" />}>
          <DepartmentFlow />
        </Panel>
        <Panel
          label="Timeline"
          icon={<ListTree className="h-3.5 w-3.5" />}
          className="max-h-[300px]"
          scroll
        >
          <TimelinePanel />
        </Panel>
      </div>
    </motion.div>
  );
}
