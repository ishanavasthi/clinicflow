"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Activity, Building2, Mic, PhoneCall, PhoneOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { connectCaller } from "@/lib/livekit";
import { fetchDepartments } from "@/lib/api";
import { useCallStore } from "@/stores/callStore";
import type { CallStatus, Department } from "@/lib/types";

const STATUS_LABEL: Record<CallStatus, string> = {
  idle: "Idle",
  ringing: "Ringing",
  connecting: "Connecting",
  active: "Active",
  "wrap-up": "Wrap-up",
  ended: "Ended",
  error: "Error",
};

function StatusBadge({ status }: { status: CallStatus }) {
  const tone =
    status === "active"
      ? "bg-emerald-500/15 text-emerald-400 ring-emerald-500/30"
      : status === "connecting"
        ? "bg-amber-500/15 text-amber-400 ring-amber-500/30"
        : status === "error"
          ? "bg-red-500/15 text-red-400 ring-red-500/30"
          : "bg-muted text-muted-foreground ring-border";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ${tone}`}
    >
      <span className="relative flex h-2 w-2">
        {status === "active" && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        )}
        <span className="relative inline-flex h-2 w-2 rounded-full bg-current" />
      </span>
      {STATUS_LABEL[status]}
    </span>
  );
}

export default function Home() {
  const { status, roomName, identity, error, setStatus, setConnection, setError, reset } =
    useCallStore();
  const [departments, setDepartments] = useState<Department[]>([]);
  const [depsError, setDepsError] = useState<string | null>(null);

  useEffect(() => {
    fetchDepartments()
      .then(setDepartments)
      .catch((e: Error) => setDepsError(e.message));
  }, []);

  const busy = status === "connecting" || status === "active";

  async function handleStart() {
    setStatus("connecting");
    try {
      const { room, info } = await connectCaller(undefined, {
        onDisconnected: () => reset(),
      });
      setConnection(room, info.room, info.identity);
      toast.success(`Connected to ${info.room}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to connect";
      setError(message);
      toast.error(message);
    }
  }

  async function handleEnd() {
    const room = useCallStore.getState().room;
    await room?.disconnect();
    reset();
    toast.message("Call ended");
  }

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-6 py-12">
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
        <StatusBadge status={status} />
      </header>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <PhoneCall className="h-4 w-4 text-primary" />
            Live Call Simulator
          </CardTitle>
          <CardDescription>
            Simulate an incoming patient call. The browser joins a LiveKit room
            over WebRTC and publishes your microphone; the AI receptionist joins
            the same room server-side.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center gap-3">
            {status !== "active" ? (
              <Button size="lg" onClick={handleStart} disabled={busy}>
                <PhoneCall className="h-4 w-4" />
                {status === "connecting" ? "Connecting..." : "Simulate incoming call"}
              </Button>
            ) : (
              <Button size="lg" variant="destructive" onClick={handleEnd}>
                <PhoneOff className="h-4 w-4" />
                End call
              </Button>
            )}
            {status === "active" && (
              <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Mic className="h-4 w-4 text-emerald-400" />
                Microphone live
              </span>
            )}
          </div>

          {status === "active" && (
            <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4 text-sm sm:grid-cols-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Room
                </p>
                <p className="font-mono">{roomName}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Identity
                </p>
                <p className="font-mono">{identity}</p>
              </div>
            </div>
          )}

          {error && (
            <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
              {error.includes("LiveKit") && (
                <span className="mt-1 block text-red-400/70">
                  Add your LiveKit credentials to server/.env and restart the API.
                </span>
              )}
            </p>
          )}
        </CardContent>
      </Card>

      <section className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium text-muted-foreground">
            Departments
          </h2>
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
                  <p className="text-xs text-muted-foreground">
                    {dept.description}
                  </p>
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

      <footer className="mt-auto pt-6 text-center text-xs text-muted-foreground/60">
        M0 scaffold. Voice pipeline (M1) and live dashboard (M3+) land next.
      </footer>
    </main>
  );
}
