"use client";

import { useEffect, useRef, useState } from "react";
import { MotionConfig, motion } from "framer-motion";
import { RoomContext } from "@livekit/components-react";
import { toast } from "sonner";
import { Mic, MicOff, PhoneCall, PhoneOff, Radio, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sidebar, type ShellView } from "@/components/shell/Sidebar";
import { WallClock } from "@/components/shell/WallClock";
import { StatusBadge } from "@/components/call/StatusBadge";
import { CallWorkspace } from "@/components/call/CallWorkspace";
import { PostCallView } from "@/components/call/PostCallView";
import { HistoryView } from "@/components/history/HistoryView";
import { connectCaller } from "@/lib/livekit";
import { fetchDepartments, uploadRecording } from "@/lib/api";
import { CallRecorder } from "@/lib/recorder";
import { useCallStore } from "@/stores/callStore";
import { fadeUp, stagger } from "@/lib/motion";
import type { Department } from "@/lib/types";

export default function Home() {
  const {
    status,
    room,
    roomName,
    error,
    muted,
    setStatus,
    setConnection,
    setError,
    setMuted,
    setRecording,
    endCall,
    reset,
  } = useCallStore();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [depsError, setDepsError] = useState<string | null>(null);
  const [view, setView] = useState<ShellView>("call");
  const recorderRef = useRef<CallRecorder | null>(null);

  useEffect(() => {
    fetchDepartments()
      .then(setDepartments)
      .catch((e: Error) => setDepsError(e.message));
  }, []);

  const busy = status === "connecting" || status === "active";
  const inCall = status === "active" && room !== null;
  const ended = status === "ended" || status === "wrap-up";

  /** Stop recording, upload it, and mark the call ended. Safe to call twice. */
  async function finalizeCall() {
    if (useCallStore.getState().status === "ended") return;
    const recorder = recorderRef.current;
    recorderRef.current = null;
    let blob: Blob | null = null;
    try {
      if (recorder) blob = await recorder.stop();
    } catch (e) {
      console.warn("recorder stop failed", e);
    }
    if (blob && blob.size > 0) {
      setRecording(URL.createObjectURL(blob));
      const callId = useCallStore.getState().callId;
      if (callId != null) {
        // Await the upload before the caller disconnects, so it persists the
        // recording_url before the agent writes the rest of the call record.
        // Otherwise the two writes race and the recording can be dropped.
        try {
          await uploadRecording(callId, blob);
        } catch (e) {
          console.warn("recording upload failed", e);
        }
      }
    }
    endCall();
  }

  async function handleStart() {
    setStatus("connecting");
    try {
      const { room: connected, info } = await connectCaller(undefined, {
        onDisconnected: () => void finalizeCall(),
      });
      setConnection(connected, info.room, info.identity);
      try {
        const recorder = new CallRecorder(connected);
        recorder.start();
        recorderRef.current = recorder;
      } catch (e) {
        console.warn("recording unavailable", e);
      }
      // If the browser still blocks audio, retry on the caller's next interaction
      // so Riya's greeting is not left silent.
      if (!connected.canPlaybackAudio) {
        toast.message("Tap anywhere to enable sound");
        const enable = () => {
          connected.startAudio().catch(() => {});
          window.removeEventListener("pointerdown", enable);
          window.removeEventListener("keydown", enable);
        };
        window.addEventListener("pointerdown", enable);
        window.addEventListener("keydown", enable);
      }
      toast.success(`Connected to ${info.room}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to connect";
      setError(message);
      toast.error(message);
    }
  }

  async function handleEnd() {
    setStatus("wrap-up");
    await finalizeCall();
    await useCallStore.getState().room?.disconnect();
    toast.message("Call ended");
  }

  function handleNewCall() {
    const url = useCallStore.getState().recordingUrl;
    if (url && url.startsWith("blob:")) URL.revokeObjectURL(url);
    reset();
  }

  async function handleToggleMute() {
    const next = !muted;
    // Disabling the mic track means the agent hears nothing and simply waits,
    // which is exactly the "give me time to think" pause.
    await room?.localParticipant.setMicrophoneEnabled(!next);
    setMuted(next);
    toast.message(next ? "Muted. Take your time, Riya will wait." : "Unmuted");
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex h-screen overflow-hidden">
        <Sidebar view={view} onSelect={setView} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border px-6">
            <div className="flex items-baseline gap-3">
              <h1 className="text-sm font-semibold tracking-tight">ClinicFlow</h1>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {view === "history" ? "Call history" : "AI Healthcare Receptionist"}
              </span>
              {view === "call" && inCall && roomName && (
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                  {roomName}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <WallClock />
              {view === "call" && <StatusBadge status={status} />}
              {view === "call" &&
                (inCall ? (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleToggleMute}
                      aria-pressed={muted}
                      className={muted ? "border-stream/40 text-stream" : ""}
                    >
                      {muted ? (
                        <MicOff className="h-4 w-4" />
                      ) : (
                        <Mic className="h-4 w-4" />
                      )}
                      {muted ? "Muted" : "Mute"}
                    </Button>
                    <Button size="sm" variant="destructive" onClick={handleEnd}>
                      <PhoneOff className="h-4 w-4" />
                      End call
                    </Button>
                  </>
                ) : ended ? (
                  <Button
                    size="sm"
                    onClick={handleNewCall}
                    disabled={status === "wrap-up"}
                  >
                    <RotateCcw className="h-4 w-4" />
                    New call
                  </Button>
                ) : (
                  <Button size="sm" onClick={handleStart} disabled={busy}>
                    <PhoneCall className="h-4 w-4" />
                    {status === "connecting" ? "Connecting..." : "Simulate call"}
                  </Button>
                ))}
            </div>
          </header>

          <main className="min-h-0 flex-1 overflow-y-auto scroll-thin px-6 py-5">
            {view === "history" ? (
              <HistoryView />
            ) : inCall && room ? (
              <RoomContext.Provider value={room}>
                <div className="flex flex-col gap-3">
                  {muted && (
                    <div className="flex items-center gap-2 rounded-lg border border-stream/30 bg-stream/10 px-3 py-2 text-xs text-stream">
                      <MicOff className="h-3.5 w-3.5 shrink-0" />
                      You are muted. Take your time; the receptionist is waiting
                      for you to reply. Unmute to answer.
                    </div>
                  )}
                  <CallWorkspace />
                </div>
              </RoomContext.Provider>
            ) : ended ? (
              <PostCallView />
            ) : (
              <IdleView
                departments={departments}
                depsError={depsError}
                error={error}
                connecting={status === "connecting"}
                onStart={handleStart}
              />
            )}
          </main>
        </div>
      </div>
    </MotionConfig>
  );
}

function IdleView({
  departments,
  depsError,
  error,
  connecting,
  onStart,
}: {
  departments: Department[];
  depsError: string | null;
  error: string | null;
  connecting: boolean;
  onStart: () => void;
}) {
  return (
    <motion.div
      variants={stagger}
      initial="hidden"
      animate="show"
      className="mx-auto flex max-w-5xl flex-col gap-8 py-6"
    >
      <motion.section
        variants={fadeUp}
        className="relative overflow-hidden rounded-2xl border border-border bg-card/70 p-10 text-center"
      >
        <div className="relative mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/20">
          <span className="absolute inset-0 animate-ping rounded-2xl bg-primary/10" />
          <Radio className="relative h-7 w-7 text-primary" />
        </div>
        <h2 className="text-xl font-semibold tracking-tight">
          The receptionist is standing by
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
          Start a call to speak with Riya. The browser joins a LiveKit room over
          WebRTC and every panel on this console updates live as she runs intake,
          books, and routes.
        </p>
        <Button size="lg" className="mt-6" onClick={onStart} disabled={connecting}>
          <PhoneCall className="h-4 w-4" />
          {connecting ? "Connecting..." : "Simulate incoming call"}
        </Button>
        {error && (
          <p className="mx-auto mt-5 max-w-md rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
            {error.includes("LiveKit") && (
              <span className="mt-1 block opacity-80">
                Add your LiveKit credentials to server/.env and restart the API.
              </span>
            )}
          </p>
        )}
      </motion.section>

      <motion.section variants={fadeUp} className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <span className="eyebrow">Departments</span>
          <span className="font-mono text-[11px] text-muted-foreground">
            {departments.length} on call
          </span>
        </div>
        {depsError ? (
          <p className="rounded-lg border border-border bg-card/60 px-4 py-3 text-sm text-muted-foreground">
            Could not reach the API ({depsError}). Start the server with{" "}
            <code className="font-mono text-xs">make server</code>.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {departments.map((dept) => (
              <div
                key={dept.id}
                className="flex flex-col gap-1 rounded-xl border border-border bg-card/60 p-4 transition-colors hover:border-primary/30"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium">{dept.name}</p>
                  <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    Fl {dept.floor}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">{dept.description}</p>
                {dept.doctors.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground/70">
                    {dept.doctors.map((d) => d.name).join(", ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </motion.section>
    </motion.div>
  );
}
