/**
 * Client-side call recorder.
 *
 * Mixes the caller's microphone and the agent's audio into one stream with the
 * Web Audio API, then captures it with MediaRecorder. This is the deliberate
 * mock for server-side recording (LiveKit Egress): no cloud egress config, and
 * the whole conversation is captured in the browser.
 */
import { Room, RoomEvent, Track } from "livekit-client";
import type { RemoteTrack, TrackPublication } from "livekit-client";

const PREFERRED_MIME = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg",
];

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  return PREFERRED_MIME.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}

export class CallRecorder {
  private ctx: AudioContext;
  private dest: MediaStreamAudioDestinationNode;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private mixed = new Set<string>();

  constructor(private room: Room) {
    this.ctx = new AudioContext();
    this.dest = this.ctx.createMediaStreamDestination();
  }

  private mix(track?: MediaStreamTrack | null) {
    if (!track || track.kind !== "audio" || this.mixed.has(track.id)) return;
    this.mixed.add(track.id);
    const source = this.ctx.createMediaStreamSource(new MediaStream([track]));
    source.connect(this.dest);
  }

  private onSubscribed = (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Audio) this.mix(track.mediaStreamTrack);
  };

  private onLocalPublished = (pub: TrackPublication) => {
    if (pub.kind === Track.Kind.Audio) this.mix(pub.track?.mediaStreamTrack);
  };

  start() {
    // Existing tracks (caller mic, and the agent audio if already subscribed).
    this.room.localParticipant.trackPublications.forEach((pub) => {
      if (pub.kind === Track.Kind.Audio) this.mix(pub.track?.mediaStreamTrack);
    });
    this.room.remoteParticipants.forEach((participant) => {
      participant.trackPublications.forEach((pub) => {
        if (pub.kind === Track.Kind.Audio) this.mix(pub.track?.mediaStreamTrack);
      });
    });

    // Tracks that arrive later (the agent joins a moment after the caller).
    this.room.on(RoomEvent.TrackSubscribed, this.onSubscribed);
    this.room.on(RoomEvent.LocalTrackPublished, this.onLocalPublished);

    const mimeType = pickMimeType();
    this.recorder = new MediaRecorder(
      this.dest.stream,
      mimeType ? { mimeType } : undefined,
    );
    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.recorder.start();
  }

  async stop(): Promise<Blob | null> {
    this.room.off(RoomEvent.TrackSubscribed, this.onSubscribed);
    this.room.off(RoomEvent.LocalTrackPublished, this.onLocalPublished);

    if (this.recorder && this.recorder.state !== "inactive") {
      await new Promise<void>((resolve) => {
        this.recorder!.onstop = () => resolve();
        this.recorder!.stop();
      });
    }
    const type = this.recorder?.mimeType || "audio/webm";
    await this.ctx.close().catch(() => {});

    if (this.chunks.length === 0) return null;
    return new Blob(this.chunks, { type });
  }
}
