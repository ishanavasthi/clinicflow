"use client";

import { useEffect, useState } from "react";
import { RoomContext } from "@livekit/components-react";
import { toast } from "sonner";
import { Activity, Building2, PhoneCall, PhoneOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StatusBadge } from "@/components/call/StatusBadge";
import { CallWorkspace } from "@/components/call/CallWorkspace";
import { connectCaller } from "@/lib/livekit";
import { fetchDepartments } from "@/lib/api";
import { useCallStore } from "@/stores/callStore";
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
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-6 px-6 py-8">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/20">
            <Activity className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">ClinicFlow</h1>
            <p className="text-xs text-muted-foreground">
              AI Healthcare Receptionist
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={status} />
          {inCall ? (
            <Button variant="destructive" onClick={handleEnd}>
              <PhoneOff className="h-4 w-4" />
              End call
            </Button>
          ) : (
            <Button onClick={handleStart} disabled={busy}>
              <PhoneCall className="h-4 w-4" />
              {status === "connecting" ? "Connecting..." : "Simulate incoming call"}
            </Button>
          )}
        </div>
      </header>

      {inCall && room ? (
        <RoomContext.Provider value={room}>
          <div className="flex items-center gap-4 rounded-lg border border-border bg-muted/20 px-4 py-2 text-xs text-muted-foreground">
            <span>
              Room <span className="font-mono text-foreground">{roomName}</span>
            </span>
            <span className="text-muted-foreground/50">
              Speak into your mic; the receptionist replies by voice and every
              panel updates live.
            </span>
          </div>
          <CallWorkspace />
        </RoomContext.Provider>
      ) : (
        <IdleView
          departments={departments}
          depsError={depsError}
          error={error}
        />
      )}
    </main>
  );
}

function IdleView({
  departments,
  depsError,
  error,
}: {
  departments: Department[];
  depsError: string | null;
  error: string | null;
}) {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PhoneCall className="h-4 w-4 text-primary" />
            Live Call Simulator
          </CardTitle>
          <CardDescription>
            Click &ldquo;Simulate incoming call&rdquo; above. The browser joins a
            LiveKit room over WebRTC and publishes your microphone; the AI
            receptionist joins the same room and the dashboard mirrors the call
            in real time.
          </CardDescription>
        </CardHeader>
        {error && (
          <CardContent>
            <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
              {error.includes("LiveKit") && (
                <span className="mt-1 block text-red-400/70">
                  Add your LiveKit credentials to server/.env and restart the API.
                </span>
              )}
            </p>
          </CardContent>
        )}
      </Card>

      <section className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium text-muted-foreground">Departments</h2>
        </div>
        {depsError ? (
          <p className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
            Could not reach the API ({depsError}). Start the server with{" "}
            <code className="font-mono text-xs">make server</code>.
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {departments.map((dept) => (
              <Card key={dept.id} className="gap-0 py-4">
                <CardContent className="flex flex-col gap-1 px-4">
                  <div className="flex items-center justify-between">
                    <p className="font-medium">{dept.name}</p>
                    <Badge variant="secondary" className="text-xs">
                      Floor {dept.floor}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{dept.description}</p>
                  {dept.doctors.length > 0 && (
                    <p className="mt-1 text-xs text-muted-foreground/80">
                      {dept.doctors.map((d) => d.name).join(", ")}
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
