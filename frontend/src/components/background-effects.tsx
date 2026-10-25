"use client";

import { useEffect } from "react";

/**
 * Flat black fallback backdrop plus a faint cursor-follow glow (set via
 * body::after in globals.css) for pages that don't mount their own animated
 * background (e.g. <Velaris>, which sits at z-[-10] — this stays further
 * back at z-[-20] so it never paints over it).
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
        zIndex: -20,
        background: "#050505",
      }}
    />
  );
}
