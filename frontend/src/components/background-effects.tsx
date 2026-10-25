"use client";

import { useEffect } from "react";

/**
 * Flat black backdrop plus a faint cursor-follow glow (set via body::after
 * in globals.css). Previously drew three drifting navy/crimson orbs; dropped
 * in favor of medal.tv's plain, minimal black, with no ambient color wash.
 */
export function BackgroundEffects() {
  useEffect(() => {
    let rafId: number | null = null;
    let lastX = 0;
    let lastY = 0;

    const onMove = (e: MouseEvent) => {
      lastX = e.clientX;
      lastY = e.clientY;
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        document.body.style.setProperty("--mx", `${lastX}px`);
        document.body.style.setProperty("--my", `${lastY}px`);
        rafId = null;
      });
    };

    document.addEventListener("mousemove", onMove);
    return () => {
      document.removeEventListener("mousemove", onMove);
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        zIndex: -1,
        background: "#050505",
      }}
    />
  );
}
