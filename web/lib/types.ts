/**
 * Shared types for the ClinicFlow dashboard.
 *
 * The AgentStateEvent union mirrors the agent-state schema published on the
 * LiveKit data channel by agent/state.py. That pair is the single dashboard
 * contract: if you change one, change the other.
 */

export type CallStatus =
  | "idle"
  | "ringing"
  | "connecting"
  | "active"
  | "wrap-up"
  | "ended"
  | "error";

export type AgentStateType =
  | "status"
  | "intake_update"
  | "faq"
  | "booking"
  | "routing"
  | "timeline";

export interface AgentStateEvent<P = Record<string, unknown>> {
  type: AgentStateType;
  call_id: string | null;
  ts: number;
  payload: P;
}

/**
 * Concrete payload shapes per event type, mirrored from agent/state.py and the
 * agent/tools/ helpers. The dashboard (M3) narrows on `type` to pick a payload.
 */
export interface StatusPayload {
  status: "active" | "ended" | string;
}

export interface IntakeUpdatePayload {
  field: string;
  value: string;
  intake: Record<string, string>;
}

export interface SlotOption {
  slot_id: number;
  doctor: string;
  when: string;
  start: string;
}

export interface BookedAppointment {
  appointment_id: number;
  patient: string;
  doctor: string;
  department: string;
  start: string;
  when: string;
  reason: string;
}

export type BookingPayload =
  | { phase: "availability"; department: string; slots: SlotOption[] }
  | { phase: "confirmed"; appointment: BookedAppointment };

export interface RoutingPayload {
  department: string;
  reason: string;
  emergency: boolean;
}

export interface FaqPayload {
  topic: string;
  raw?: string;
}

export interface TokenResponse {
  token: string;
  url: string;
  room: string;
  identity: string;
}

export interface Doctor {
  id: number;
  name: string;
  specialty: string;
}

export interface Department {
  id: number;
  name: string;
  floor: string;
  description: string;
  doctors: Doctor[];
}

export interface FAQ {
  id: number;
  question: string;
  answer: string;
  tag: string;
}
