"use client";

import { BarVisualizer, useVoiceAssistant } from "@livekit/components-react";

/** Audio-reactive bars driven by the agent's live voice track. */
export function AgentAudioVisualizer() {
  const { state, audioTrack } = useVoiceAssistant();

  return (
    <div className="clinic-visualizer h-7 w-24">
      <BarVisualizer
        state={state}
        track={audioTrack}
        barCount={9}
        options={{ minHeight: 8 }}
      />
    </div>
  );
}
