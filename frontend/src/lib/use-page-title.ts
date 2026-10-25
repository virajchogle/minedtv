"use client";

import { useEffect } from "react";

/**
 * Sets a unique, descriptive document title per route (WCAG 2.4.2 "Page
 * Titled") so screen readers announce which page loaded, and restores the
 * site default on unmount. Every page here is a client component end to
 * end, so there's no server render for Next's metadata API to improve on;
 * this is the same outcome with no risk of touching the page's markup/CSS.
 */
export function usePageTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} — MinedIt`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
