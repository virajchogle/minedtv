"use client";

/**
 * Chooses the chrome for a route.
 *
 * Legacy app routes (eval, settings, the single-video page) keep the old
 * fixed Sidebar and scroll inside <main>. The redesigned routes — home,
 * explore, library, upload, profile — render their own SiteNav and must NOT
 * also get the Sidebar: the Sidebar is `fixed` with `pl-16` compensation on
 * <main>, so stacking it under a page that already has its own full-bleed
 * nav produced the layout clash ("switches back to the old UI") these pages
 * were built to replace.
 */

import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { Sidebar } from "@/components/sidebar";
import { warmup } from "@/lib/api";

const BARE_ROUTES = new Set(["/", "/explore", "/library", "/upload", "/profile"]);

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

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

  if (BARE_ROUTES.has(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen">
      {/* Fixed sidebar — out of normal flow, main gets pl-16 to compensate */}
      <Sidebar />
      <main className="flex-1 overflow-y-auto pl-16">{children}</main>
    </div>
  );
}
