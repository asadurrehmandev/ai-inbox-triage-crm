"use client";

import { useEffect, useState } from "react";

export function useDelayed(active: boolean, ms = 150) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(() => setReady(true), ms);
    return () => window.clearTimeout(timer);
  }, [active, ms]);
  return active && ready;
}
