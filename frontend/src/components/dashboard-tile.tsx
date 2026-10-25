"use client";

import type { ReactNode } from "react";

import { BorderBeam } from "@/components/ui/border-beam";
import { cn } from "@/lib/utils";

/** Hover/focus reveals the traveling border. Used for the 2×2 tiles and the small stat squares. */
export function HoverBeam({
  children,
  className,
  as: Comp = "div",
  onClick,
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "button";
  onClick?: () => void;
}) {
  const interactive = Comp === "button";
  return (
    <Comp
      {...(interactive ? { type: "button" as const, onClick } : {})}
      className={cn("group/beam min-h-0 h-full w-full text-left", interactive && "cursor-pointer")}
    >
      <BorderBeam
        color="#cbff3d"
        colorTo="#3ddc84"
        className={cn(
          "flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-[var(--mtv-surface)] p-1",
          // The beam's traveling-ring overlay paints after this panel in the DOM, so without this
          // gap it sits flush on top of any edge-hugging content (e.g. NeonFrame's corner tabs)
          // and visually clips it. The gap keeps the two border decorations from touching.
          "[&_.nk-beam]:opacity-0 [&_.nk-beam]:transition-opacity",
          "group-hover/beam:[&_.nk-beam]:opacity-100 group-focus-visible/beam:[&_.nk-beam]:opacity-100",
          className
        )}
      >
        {children}
      </BorderBeam>
    </Comp>
  );
}
