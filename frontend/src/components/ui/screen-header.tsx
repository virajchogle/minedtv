"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

export function ScreenTitle({
  children,
  action,
  className,
}: {
  children: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between", className)}>
      <h1 className="text-[26px] font-extrabold tracking-tight text-[var(--mtv-text)]">
        {children}
      </h1>
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
