/**
 * Zustand store for realtime call state.
 *
 * M0 tracks connection lifecycle only. Transcript, intake, routing, and
 * timeline slices are added as later milestones wire the agent-state channel.
 */
import { create } from "zustand";
import type { Room } from "livekit-client";
import type { CallStatus } from "@/lib/types";

interface CallState {
  status: CallStatus;
  room: Room | null;
  roomName: string | null;
  identity: string | null;
  error: string | null;

  setStatus: (status: CallStatus) => void;
  setConnection: (room: Room, roomName: string, identity: string) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useCallStore = create<CallState>((set) => ({
  status: "idle",
  room: null,
  roomName: null,
  identity: null,
  error: null,

  setStatus: (status) => set({ status }),
  setConnection: (room, roomName, identity) =>
    set({ room, roomName, identity, status: "active", error: null }),
  setError: (error) => set({ error, status: error ? "error" : "idle" }),
  reset: () =>
    set({
      status: "idle",
      room: null,
      roomName: null,
      identity: null,
      error: null,
    }),
}));
