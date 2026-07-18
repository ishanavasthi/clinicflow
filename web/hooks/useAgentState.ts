/**
 * Subscribes to the "agent-state" data channel and folds each event into the
 * call store. Must be used inside a RoomContext (the LiveKit React provider).
 */
import { useDataChannel } from "@livekit/components-react";
import { useCallStore } from "@/stores/callStore";
import type { AgentStateEvent } from "@/lib/types";

const decoder = new TextDecoder();

export function useAgentState(): void {
  const applyEvent = useCallStore((s) => s.applyEvent);

  useDataChannel("agent-state", (msg) => {
    try {
      const event = JSON.parse(decoder.decode(msg.payload)) as AgentStateEvent;
      applyEvent(event);
    } catch (err) {
      console.warn("dropped malformed agent-state event", err);
    }
  });
}
