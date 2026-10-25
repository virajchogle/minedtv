"use client";

import { useEffect } from "react";

/**
 * Dev-only: runs axe-core against the live DOM after each render and logs
 * violations to the browser console. Never runs in production (no bundle
 * cost, no runtime cost); see README/A11Y notes for how to read its output.
 */
export function AxeDev() {
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    let cancelled = false;
    Promise.all([import("@axe-core/react"), import("react"), import("react-dom")]).then(
      ([{ default: axe }, React, ReactDOM]) => {
        if (cancelled) return;
        axe(React, ReactDOM, 1000);
      }
    );
    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
