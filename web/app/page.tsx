"use client";

import { useEffect, useState } from "react";
import { MotionConfig, motion } from "framer-motion";
import { RoomContext } from "@livekit/components-react";
import { toast } from "sonner";
import { PhoneCall, PhoneOff, Radio } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sidebar } from "@/components/shell/Sidebar";
import { WallClock } from "@/components/shell/WallClock";
import { StatusBadge } from "@/components/call/StatusBadge";
import { CallWorkspace } from "@/components/call/CallWorkspace";
import { connectCaller } from "@/lib/livekit";
import { fetchDepartments } from "@/lib/api";
import { useCallStore } from "@/stores/callStore";
import { fadeUp, stagger } from "@/lib/motion";
import type { Department } from "@/lib/types";

export default function Home() {
  const { status, room, roomName, error, setStatus, setConnection, setError, reset } =
    useCallStore();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [depsError, setDepsError] = useState<string | null>(null);

  useEffect(() => {
    fetchDepartments()
      .then(setDepartments)
      .catch((e: Error) => setDepsError(e.message));
  }, []);

  const busy = status === "connecting" || status === "active";
  const inCall = status === "active" && room !== null;

  async function handleStart() {
    setStatus("connecting");
    try {
      const { room: connected, info } = await connectCaller(undefined, {
        onDisconnected: () => reset(),
      });
      setConnection(connected, info.room, info.identity);
      toast.success(`Connected to ${info.room}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to connect";
      setError(message);
      toast.error(message);
    }
  }

  async function handleEnd() {
    await useCallStore.getState().room?.disconnect();
    reset();
    toast.message("Call ended");
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border px-6">
            <div className="flex items-baseline gap-3">
              <h1 className="text-sm font-semibold tracking-tight">ClinicFlow</h1>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                AI Healthcare Receptionist
              </span>
              {inCall && roomName && (
                <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                  {roomName}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <WallClock />
              <StatusBadge status={status} />
              {inCall ? (
                <Button size="sm" variant="destructive" onClick={handleEnd}>
                  <PhoneOff className="h-4 w-4" />
                  End call
                </Button>
              ) : (
                <Button size="sm" onClick={handleStart} disabled={busy}>
                  <PhoneCall className="h-4 w-4" />
                  {status === "connecting" ? "Connecting..." : "Simulate call"}
                </Button>
              )}
            </div>
          </header>

          <main className="min-h-0 flex-1 overflow-y-auto scroll-thin px-6 py-5">
            {inCall && room ? (
              <RoomContext.Provider value={room}>
                <CallWorkspace />
              </RoomContext.Provider>
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
