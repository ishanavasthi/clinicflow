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
  call_id: string;
  ts: number;
  payload: P;
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
