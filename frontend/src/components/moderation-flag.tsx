"use client";

import { Flag } from "lucide-react";

import { formatTimestamp, type ModerationViolationOut } from "@/lib/api";

/**
 * Red flag box: "this video violates our code of conduct," itemized by rule
 * and timestamp. Used wherever a clip/session has moderation_violations;
 * the upload flow, clip detail, My Library.
 */
export function ModerationFlag({
  reason,
  violations,
}: {
  reason: string | null;
  violations: ModerationViolationOut[];
}) {
  if (!reason && violations.length === 0) return null;

  return (
    <div className="space-y-2 rounded-xl border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3">
      <div className="flex items-start gap-2 text-sm text-[var(--mtv-red)]">
        <Flag className="mt-0.5 h-4 w-4 shrink-0 fill-current" />
        <p>
          <span className="font-semibold">This video violates our code of conduct.</span>
          {reason && <span className="text-[var(--mtv-red)]/85"> {reason}</span>}
        </p>
      </div>

      {violations.length > 0 && (
        <ul className="space-y-1 border-t border-[var(--mtv-red)]/20 pt-2">
          {violations.map((v, i) => (
            <li key={i} className="flex gap-2 text-xs text-[var(--mtv-red)]/85">
              <span className="shrink-0 rounded bg-[var(--mtv-red)]/15 px-1.5 py-0.5 font-mono font-semibold">
                {v.timestamp_ms !== null ? formatTimestamp(v.timestamp_ms / 1000) : "general"}
              </span>
              <span>
                <span className="font-semibold capitalize">{v.category.replace(/_/g, " ")}:</span> {v.note}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
