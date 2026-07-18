"use client";

import { useEffect, useState } from "react";

/** Wall-clock time in the top bar. Empty on first paint to avoid hydration drift. */
export function WallClock() {
  const [now, setNow] = useState("");

  useEffect(() => {
    const tick = () =>
      setNow(
        new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      );
    tick();
    const id = setInterval(tick, 15000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="font-mono text-xs tabular-nums text-muted-foreground">
      {now}
    </span>
  );
}
