"use client";

/**
 * Who the app is acting as. The backend has no login yet: every request
 * carries X-User-Id for the chosen user (see `request()` in lib/api.ts).
 * The switcher lists the demo users and can create a new one.
 */

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, Plus, UserRound } from "lucide-react";

import {
  USER_CHANGED_EVENT,
  createUser,
  fetchUsers,
  getCurrentUser,
  setCurrentUser,
} from "@/lib/api";
import type { UserOut } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

/** The current user, kept in sync across components and tabs. */
export function useCurrentUser(): UserOut | null {
  const [user, setUser] = useState<UserOut | null>(null);
  useEffect(() => {
    const sync = () => setUser(getCurrentUser());
    sync();
    window.addEventListener(USER_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(USER_CHANGED_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return user;
}

export function UserSwitcher({ compact = false, className }: { compact?: boolean; className?: string }) {
  const me = useCurrentUser();
  const [open, setOpen] = useState(false);
  const [users, setUsers] = useState<UserOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || users) return;
    fetchUsers()
      .then(setUsers)
      .catch((e: Error) => setError(e.message));
  }, [open, users]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const choose = (user: UserOut) => {
    setCurrentUser(user);
    setOpen(false);
  };

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      const user = await createUser(name);
      setUsers((list) => [...(list ?? []), user]);
      setNewName("");
      choose(user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create user");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm text-white/85 transition-colors hover:bg-white/10"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {me?.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={me.avatar_url} alt="" className="h-5 w-5 rounded-full" />
        ) : (
          <UserRound className="h-4 w-4" />
        )}
        {!compact && <span className="max-w-[9rem] truncate">{me ? me.username : "Choose user"}</span>}
        <ChevronDown className="h-3.5 w-3.5 opacity-70" />
      </button>

      {open && (
        <div className="absolute right-0 z-[70] mt-2 w-64 rounded-xl border border-white/10 bg-black/90 p-2 shadow-2xl backdrop-blur-xl">
          <p className="px-2 pb-1.5 text-[11px] uppercase tracking-wider text-white/45">Acting as</p>
          {!users && !error && (
            <div className="flex items-center gap-2 px-2 py-2 text-sm text-white/60">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading users…
            </div>
          )}
          <div className="max-h-64 overflow-y-auto" role="listbox">
            {users?.map((user) => (
              <button
                key={user.id}
                type="button"
                role="option"
                aria-selected={me?.id === user.id}
                onClick={() => choose(user)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-white/85 hover:bg-white/10"
              >
                {user.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={user.avatar_url} alt="" className="h-5 w-5 rounded-full" />
                ) : (
                  <UserRound className="h-4 w-4 text-white/50" />
                )}
                <span className="flex-1 truncate">{user.username}</span>
                {me?.id === user.id && <Check className="h-4 w-4 text-[var(--mtv-gold)]" />}
              </button>
            ))}
          </div>
          <div className="mt-2 flex gap-1.5 border-t border-white/10 pt-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void create()}
              placeholder="New username"
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-white placeholder:text-white/35 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => void create()}
              disabled={creating || !newName.trim()}
              className="rounded-lg bg-[var(--mtv-gold)] px-2 text-[var(--mtv-on-gold)] disabled:opacity-40"
              aria-label="Create user"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            </button>
          </div>
          {error && <p className="px-2 pt-1.5 text-xs text-[var(--mtv-red)]">{error}</p>}
          {me && (
            <button
              type="button"
              onClick={() => {
                setCurrentUser(null);
                setOpen(false);
              }}
              className="mt-1 w-full rounded-lg px-2 py-1.5 text-left text-xs text-white/50 hover:bg-white/10"
            >
              Stop acting as {me.username}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Shown in place of owner-only content when no user is chosen. */
export function ChooseUserNotice({ action }: { action: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-[var(--mtv-divider)] p-4 text-sm text-[var(--mtv-text-2)]">
      <span>Choose who you are to {action}.</span>
      <UserSwitcher />
    </div>
  );
}
