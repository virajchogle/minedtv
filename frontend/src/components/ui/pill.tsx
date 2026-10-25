"use client";

import { cn } from "@/lib/utils";

export function Pill({
  selected,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { selected?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        "shrink-0 rounded-full px-4 py-2 text-[13px] font-semibold transition-colors",
        selected
          ? "bg-[var(--mtv-gold)] text-[var(--mtv-on-gold)]"
          : "bg-[var(--mtv-surface-high)] text-[var(--mtv-text)] hover:bg-[var(--mtv-surface-high)]/70",
        className
      )}
      {...props}
    />
  );
}

export function PillRow({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className
      )}
    >
      {children}
    </div>
  );
}
