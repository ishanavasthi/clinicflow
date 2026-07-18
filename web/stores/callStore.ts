/**
 * Zustand store for realtime call state.
 *
 * Connection lifecycle plus the live slices the dashboard renders. `applyEvent`
 * folds each agent-state event (published by agent/state.py over the data
 * channel) into the store, so every panel is a pure subscriber.
 */
import { create } from "zustand";
import type { Room } from "livekit-client";
import type {
  AgentStateEvent,
  BookedAppointment,
  BookingPayload,
  CallStatus,
  IntakeUpdatePayload,
  RoutingPayload,
  SlotOption,
  StatusPayload,
} from "@/lib/types";

export interface TimelineEntry {
  id: string;
  type: AgentStateEvent["type"];
  ts: number;
  label: string;
  emphasis?: "normal" | "success" | "alert";
}

interface CallState {
  // Connection
  status: CallStatus;
  room: Room | null;
  roomName: string | null;
  identity: string | null;
  callerIdentity: string | null;
  error: string | null;
  muted: boolean;

  // Live call data, driven by agent-state events
  intake: Record<string, string>;
  patientId: number | null;
  callId: number | null;
  recordingUrl: string | null;
  offeredSlots: SlotOption[];
  offeredDepartment: string | null;
  booking: BookedAppointment | null;
  routing: RoutingPayload | null;
  timeline: TimelineEntry[];

  // Actions
  setStatus: (status: CallStatus) => void;
  setConnection: (room: Room, roomName: string, identity: string) => void;
  setError: (error: string | null) => void;
  setMuted: (muted: boolean) => void;
  setIntakeFields: (fields: Record<string, string>) => void;
  setRecording: (url: string | null) => void;
  endCall: () => void;
  applyEvent: (event: AgentStateEvent) => void;
  reset: () => void;
}

const INITIAL_DATA = {
  intake: {},
  patientId: null as number | null,
  callId: null as number | null,
  recordingUrl: null as string | null,
  offeredSlots: [] as SlotOption[],
  offeredDepartment: null as string | null,
  booking: null as BookedAppointment | null,
  routing: null as RoutingPayload | null,
  timeline: [] as TimelineEntry[],
};

export const useCallStore = create<CallState>((set) => ({
  status: "idle",
  room: null,
  roomName: null,
  identity: null,
  callerIdentity: null,
  error: null,
  muted: false,
  ...INITIAL_DATA,

  setStatus: (status) => set({ status }),

  setConnection: (room, roomName, identity) =>
    set({
      room,
      roomName,
      identity,
      callerIdentity: identity,
      status: "active",
      error: null,
      muted: false,
      ...INITIAL_DATA,
    }),

  setError: (error) => set({ error, status: error ? "error" : "idle" }),

  setMuted: (muted) => set({ muted }),

  setIntakeFields: (fields) =>
    set((state) => ({ intake: { ...state.intake, ...fields } })),

  setRecording: (recordingUrl) => set({ recordingUrl }),

  // Keep the collected data and transcript for the post-call view; just mark ended.
  endCall: () => set({ status: "ended", muted: false }),

  applyEvent: (event) =>
    set((state) => reduceEvent(state, event)),

  reset: () =>
    set({
      status: "idle",
      room: null,
      roomName: null,
      identity: null,
      callerIdentity: null,
      error: null,
      muted: false,
      ...INITIAL_DATA,
    }),
}));

function pushTimeline(
  state: CallState,
  entry: Omit<TimelineEntry, "id" | "ts"> & { ts: number },
): TimelineEntry[] {
  const id = `${entry.ts}-${entry.type}-${state.timeline.length}`;
  return [...state.timeline, { id, ...entry }];
}

/** Reduce one agent-state event into a partial store update. */
function reduceEvent(
  state: CallState,
  event: AgentStateEvent,
): Partial<CallState> {
  const ts = event.ts;
  switch (event.type) {
    case "status": {
      const payload = event.payload as unknown as StatusPayload & {
        call_id?: number | null;
      };
      if (payload.status === "ended") {
        return {
          timeline: pushTimeline(state, {
            type: "status",
            ts,
            label: "Call ended",
          }),
        };
      }
      // "active" carries the numeric call id so the dashboard can upload a recording.
      if (payload.call_id != null) return { callId: payload.call_id };
      return {};
    }

    case "intake_update": {
      const payload = event.payload as unknown as IntakeUpdatePayload;
      return {
        intake: { ...state.intake, ...payload.intake },
        patientId: payload.patient_id ?? state.patientId,
        timeline: pushTimeline(state, {
          type: "intake_update",
          ts,
          label: `Collected ${payload.field}`,
        }),
      };
    }

    case "booking": {
      const payload = event.payload as unknown as BookingPayload;
      if (payload.phase === "availability") {
        return {
          offeredSlots: payload.slots,
          offeredDepartment: payload.department,
          timeline: pushTimeline(state, {
            type: "booking",
            ts,
            label:
              payload.slots.length > 0
                ? `Checked availability: ${payload.department}`
                : `No slots in ${payload.department}`,
          }),
        };
      }
      return {
        booking: payload.appointment,
        timeline: pushTimeline(state, {
          type: "booking",
          ts,
          label: `Booked ${payload.appointment.doctor}`,
          emphasis: "success",
        }),
      };
    }

    case "routing": {
      const payload = event.payload as unknown as RoutingPayload;
      return {
        routing: payload,
        timeline: pushTimeline(state, {
          type: "routing",
          ts,
          label: `Routed to ${payload.department}`,
          emphasis: payload.emergency ? "alert" : "normal",
        }),
      };
    }

    case "faq": {
      const topic = (event.payload as { topic?: string }).topic ?? "question";
      return {
        timeline: pushTimeline(state, {
          type: "faq",
          ts,
          label: `Answered FAQ: ${topic}`,
        }),
      };
    }

    default:
      return {};
  }
}
