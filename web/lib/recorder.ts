/**
 * Client-side call recorder.
 *
 * Mixes the caller's microphone and the agent's audio with the Web Audio API,
 * taps the mixed samples, and encodes them as a 16 kHz mono WAV. This is the
 * deliberate mock for server-side recording (LiveKit Egress): no cloud egress
 * config, the whole conversation is captured in the browser.
 *
 * WAV, not MediaRecorder's webm/opus, on purpose: webm/opus does not play in
 * macOS QuickTime or Finder once downloaded, and MediaRecorder never writes a
 * duration into the container, so the <audio> scrub bar is dead even for good
 * takes. A PCM WAV plays in every browser and desktop player and carries a real
 * duration header. 16 kHz mono is phone grade: intelligible voice, small files.
 */
import { Room, RoomEvent, Track } from "livekit-client";
import type { RemoteTrack, TrackPublication } from "livekit-client";

const TARGET_SAMPLE_RATE = 16000;

type AudioContextCtor = typeof AudioContext;

function createContext(): AudioContext {
  const Ctor: AudioContextCtor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: AudioContextCtor })
      .webkitAudioContext;
  try {
    // A fixed low rate keeps files small; source nodes resample into it for us.
    return new Ctor({ sampleRate: TARGET_SAMPLE_RATE });
  } catch {
    // Some browsers reject a forced rate; fall back to the hardware default.
    return new Ctor();
  }
}

function writeString(view: DataView, offset: number, text: string) {
  for (let i = 0; i < text.length; i++) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

/** Encode mono Float32 chunks into a 16-bit PCM WAV blob. */
function encodeWav(
  chunks: Float32Array[],
  length: number,
  sampleRate: number,
): Blob {
  const dataBytes = length * 2;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true); // PCM header length
  view.setUint16(20, 1, true); // format: PCM
  view.setUint16(22, 1, true); // channels: mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate (rate * blockAlign)
  view.setUint16(32, 2, true); // block align (channels * bytesPerSample)
  view.setUint16(34, 16, true); // bits per sample
  writeString(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  let offset = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }

  return new Blob([view], { type: "audio/wav" });
}

export class CallRecorder {
  private ctx: AudioContext;
  private sink: GainNode;
  private processor: ScriptProcessorNode | null = null;
  private chunks: Float32Array[] = [];
  private length = 0;
  private mixed = new Set<string>();

  constructor(private room: Room) {
    this.ctx = createContext();
    // A zero-gain sink keeps the graph pulling audio through the processor
    // without echoing the caller's mic or doubling the agent back to the room.
    this.sink = this.ctx.createGain();
    this.sink.gain.value = 0;
    this.sink.connect(this.ctx.destination);
  }

  private mix(track?: MediaStreamTrack | null) {
    if (!track || track.kind !== "audio" || this.mixed.has(track.id)) return;
    if (!this.processor) return;
    this.mixed.add(track.id);
    const source = this.ctx.createMediaStreamSource(new MediaStream([track]));
    // Both parties sum into the single mono processor input.
    source.connect(this.processor);
  }

  private onSubscribed = (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Audio) this.mix(track.mediaStreamTrack);
  };

  private onLocalPublished = (pub: TrackPublication) => {
    if (pub.kind === Track.Kind.Audio) this.mix(pub.track?.mediaStreamTrack);
  };

  start() {
    // The Start Call click is the user gesture that lets a suspended context
    // resume; without this the processor never fires and the take is silent.
    void this.ctx.resume().catch(() => {});

    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(input));
      this.length += input.length;
    };
    this.processor.connect(this.sink);

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
  }

  async stop(): Promise<Blob | null> {
    this.room.off(RoomEvent.TrackSubscribed, this.onSubscribed);
    this.room.off(RoomEvent.LocalTrackPublished, this.onLocalPublished);

    if (this.processor) {
      this.processor.onaudioprocess = null;
      this.processor.disconnect();
    }
    this.sink.disconnect();

    const sampleRate = this.ctx.sampleRate;
    await this.ctx.close().catch(() => {});

    // No audio flowed (e.g. the caller hung up on connect): let the UI show its
    // empty state instead of a valid-but-silent file that looks broken.
    if (this.length === 0) return null;
    return encodeWav(this.chunks, this.length, sampleRate);
  }
}
