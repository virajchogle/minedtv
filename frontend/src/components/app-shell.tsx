"use client";

/**
 * Wraps every page: confirms the login cookie and wakes the GPU embedder once per tab.
 * Each page renders its own top navigation (SiteNav).
 */

import { useEffect } from "react";

import { refreshAccount, warmup } from "@/lib/api";


export function AppShell({ children }: { children: React.ReactNode }) {

  // Confirm the login cookie is still good (or drop a stale signed-in state).
  useEffect(() => {
    void refreshAccount();
  }, []);

  // Wake the GPU embedder once per tab, so the first search isn't a 15-30 s cold start.
  useEffect(() => {
    try {
      if (sessionStorage.getItem("minedtv-warm")) return;
      sessionStorage.setItem("minedtv-warm", "1");
    } catch {
      /* storage unavailable: warm anyway */
    }
    warmup();
  }, []);

  return <>{children}</>;
}
