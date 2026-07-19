/** LiveKit room connection helpers for the caller pane. */
import { Room, RoomEvent } from "livekit-client";
import { fetchToken } from "./api";
import type { TokenResponse } from "./types";

export interface CallerConnection {
  room: Room;
  info: TokenResponse;
}

/**
 * Mint a caller token from the server and join the LiveKit room, publishing the
 * microphone. The agent worker auto-joins the same room server-side.
 */
export async function connectCaller(
  roomName?: string,
  handlers?: {
    onConnected?: (room: Room) => void;
    onDisconnected?: () => void;
  },
): Promise<CallerConnection> {
  const info = await fetchToken("caller", roomName);

  const room = new Room({ adaptiveStream: true, dynacast: true });

  if (handlers?.onConnected) {
    room.on(RoomEvent.Connected, () => handlers.onConnected?.(room));
  }
  if (handlers?.onDisconnected) {
    room.on(RoomEvent.Disconnected, () => handlers.onDisconnected?.());
  }

  await room.connect(info.url, info.token);
  await room.localParticipant.setMicrophoneEnabled(true);

  // Unlock audio playback within the user's click gesture, so the agent's
  // greeting is heard immediately. Browsers block autoplay until a gesture; the
  // agent's audio track arrives after this async connect, so without this the
  // greeting is silent until the caller interacts. Best-effort: if it is still
  // blocked, the caller-side fallback listener retries on the next interaction.
  await room.startAudio().catch(() => {});

  return { room, info };
}
