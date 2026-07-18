"use client";

import { useEffect, useState } from "react";

function format(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

/** Counts up for the duration of the call. Mounted only while a call is active. */
export function CallTimer() {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(
      () => setSeconds(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, []);

  return <span className="font-mono text-sm tabular-nums">{format(seconds)}</span>;
}
