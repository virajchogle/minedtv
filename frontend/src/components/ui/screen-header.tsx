"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * Page heading in the home page's voice: heavy display type, uppercase, with an optional accent
 * phrase in the brand colour, a small eyebrow above and a muted line below.
 */
export function ScreenTitle({
  children,
  accent,
  eyebrow,
  subtitle,
  action,
  className,
}: {
  children: React.ReactNode;
  accent?: React.ReactNode;
  eyebrow?: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-6", className)}>
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-3 font-mono text-[11px] uppercase tracking-[0.25em] text-[var(--mtv-gold)]">{eyebrow}</p>
        )}
        <h1 className="font-display text-balance text-4xl uppercase leading-[0.95] tracking-tight text-[var(--mtv-text)] sm:text-6xl">
          {children}
          {accent && <span className="text-[var(--mtv-gold)]"> {accent}</span>}
        </h1>
        {subtitle && <p className="mt-4 max-w-xl text-base text-white/55 sm:text-lg">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function SectionHeader({
  title,
  actionLabel,
  actionHref,
  className,
}: {
  title: string;
  actionLabel?: string;
  actionHref?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between", className)}>
      <h2 className="text-lg font-bold text-[var(--mtv-text)]">{title}</h2>
      {actionLabel && actionHref && (
        <Link
          href={actionHref}
          className="text-[13px] font-semibold text-[var(--mtv-gold)] hover:opacity-80"
        >
          {actionLabel}
        </Link>
      )}
    </div>
  );
}
