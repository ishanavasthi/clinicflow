"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
import {
  CalendarClock,
  CircleCheck,
  ClipboardList,
  ListTree,
  PlayCircle,
  Split,
  UserRound,
} from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { stagger } from "@/lib/motion";
import { RecordingPlayer } from "@/components/call/RecordingPlayer";
import { IntakePanel } from "@/components/patient/IntakePanel";
import { AppointmentPanel } from "@/components/appointments/AppointmentPanel";
import { DepartmentFlow } from "@/components/routing/DepartmentFlow";
import { TimelinePanel } from "@/components/timeline/TimelinePanel";
import { DoctorSummaryCard } from "@/components/summary/DoctorSummaryCard";
import { fetchCall } from "@/lib/api";
import { useCallStore } from "@/stores/callStore";

// The doctor summary is written after hang-up, when this page has already left
// the room, so it is read from the saved call record instead.
const SUMMARY_POLL_MS = 2500;
const SUMMARY_POLL_TRIES = 8;

function useSavedDoctorSummary(): void {
  const callId = useCallStore((s) => s.callId);
  const doctorSummary = useCallStore((s) => s.doctorSummary);
  useSavedDoctorSummary();
  const setDoctorSummary = useCallStore((s) => s.setDoctorSummary);

  useEffect(() => {
    if (callId == null || doctorSummary) return;
    let cancelled = false;
    let tries = 0;
    const poll = async () => {
      tries += 1;
      try {
        const call = await fetchCall(callId);
        if (cancelled) return;
        if (call.summary?.doctor_summary) {
          setDoctorSummary(call.summary.doctor_summary);
          return;
        }
        // Saved without a language: an English-only clinic, no summary coming.
        if (call.status === "ended" && call.summary && !call.summary.language) return;
      } catch {
        // The server may still be writing the record; try again.
      }
      if (!cancelled && tries < SUMMARY_POLL_TRIES) timer = setTimeout(poll, SUMMARY_POLL_MS);
    };
    let timer = setTimeout(poll, SUMMARY_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [callId, doctorSummary, setDoctorSummary]);
}

/** The post-call summary. Panels read the store, so no live room is needed. */
export function PostCallView() {
  const intake = useCallStore((s) => s.intake);
  const booking = useCallStore((s) => s.booking);
  const routing = useCallStore((s) => s.routing);
  const doctorSummary = useCallStore((s) => s.doctorSummary);
  useSavedDoctorSummary();

  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="grid flex-1 gap-4 lg:grid-cols-12"
    >
      <div className="flex flex-col gap-4 lg:col-span-5">
        <Panel label="Recording" icon={<PlayCircle className="h-3.5 w-3.5" />}>
          <RecordingPlayer />
        </Panel>
        <Panel label="Call summary" icon={<CircleCheck className="h-3.5 w-3.5" />}>
          <ul className="flex flex-col gap-1.5 text-sm">
            <li className="flex justify-between gap-3">
              <span className="text-muted-foreground">Patient</span>
              <span>{intake.name ?? "Not captured"}</span>
            </li>
            <li className="flex justify-between gap-3">
              <span className="text-muted-foreground">Outcome</span>
              <span className="text-right">
                {booking
                  ? `Booked with ${booking.doctor}`
                  : routing
                    ? `Routed to ${routing.department}`
                    : "No booking"}
              </span>
            </li>
            {booking && (
              <li className="flex justify-between gap-3">
                <span className="text-muted-foreground">When</span>
                <span className="text-right font-mono text-xs">{booking.when}</span>
              </li>
            )}
          </ul>
        </Panel>
        {doctorSummary && (
          <Panel label="Doctor summary" icon={<ClipboardList className="h-3.5 w-3.5" />}>
            <DoctorSummaryCard summary={doctorSummary} />
          </Panel>
        )}
      </div>

      <div className="flex flex-col gap-4 lg:col-span-4">
        <Panel label="Patient intake" icon={<UserRound className="h-3.5 w-3.5" />}>
          <IntakePanel />
        </Panel>
        <Panel label="Appointment" icon={<CalendarClock className="h-3.5 w-3.5" />}>
          <AppointmentPanel />
        </Panel>
      </div>

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
