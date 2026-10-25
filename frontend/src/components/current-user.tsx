"use client";

/**
 * The account menu in the nav, and hooks for who's signed in.
 *
 * "Act as" picks the user requests act as: every request then carries
 * X-User-Id for them (see `request()` in lib/api.ts). While the server
 * doesn't require login (testing), everyone gets it, signed in or not, so
 * the demo users (ShadowSniper and co.) are one click away. Once login is
 * required, only dev accounts keep it and signed-out visitors see "Sign in".
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Check, ChevronDown, Loader2, LogIn, LogOut, Plus, UserRound } from "lucide-react";

import {
  USER_CHANGED_EVENT,
  actAsOpen,
  createUser,
  fetchUsers,
  getAccount,
  getCurrentUser,
  setCurrentUser,
  signOut,
} from "@/lib/api";
import type { MeOut, UserOut } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

function subscribe(onChange: () => void): () => void {
  window.addEventListener(USER_CHANGED_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(USER_CHANGED_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** Reads identity synchronously on the client (null during server render and hydration). */
function useStored<T>(read: () => T | null): T | null {
  // Snapshots must be referentially stable, so re-parse only when the stored JSON changes.
  const cache = useRef<{ json: string; value: T | null } | null>(null);
  const getSnapshot = () => {
    const value = read();
    const json = JSON.stringify(value);
    if (cache.current?.json !== json) cache.current = { json, value };
    return cache.current.value;
  };
  return useSyncExternalStore(subscribe, getSnapshot, () => null);
}

/** Who requests act as (the account itself, or whoever a dev account picked). */
export function useCurrentUser(): UserOut | null {
  return useStored(getCurrentUser);
}

/** The signed-in account. */
export function useAccount(): MeOut | null {
  return useStored(getAccount);
}

/** Whether anyone may act as anyone (server doesn't require login). */
export function useActAsOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let cancelled = false;
    void actAsOpen().then((v) => !cancelled && setOpen(v));
    return () => {
      cancelled = true;
    };
  }, []);
  return open;
}

/** /login, returning here afterwards. */
export function useLoginHref(): string {
  const pathname = usePathname();
  return pathname && pathname !== "/login" ? `/login?next=${encodeURIComponent(pathname)}` : "/login";
}

function Avatar({ user, className }: { user: UserOut | null; className?: string }) {
  return user?.avatar_url ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={user.avatar_url} alt="" className={cn("h-5 w-5 rounded-full", className)} />
  ) : (
    <UserRound className={cn("h-4 w-4", className)} />
  );
}

export function UserSwitcher({
  compact = false,
  up = false,
  className,
}: {
  compact?: boolean;
  /** Open the menu upwards (for the bottom of the sidebar). */
  up?: boolean;
  className?: string;
}) {
  const account = useAccount();
  const me = useCurrentUser();
  const loginHref = useLoginHref();
  const openMode = useActAsOpen();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

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

  if (!account && !openMode) {
    return (
      <Link
        href={loginHref}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-sm text-white/85 transition-colors hover:bg-white/10",
          className
        )}
      >
        <LogIn className="h-4 w-4" />
        {!compact && <span>Sign in</span>}
      </Link>
    );
  }

  const actingAsOther = Boolean(account && me && me.id !== account.id);
  const canActAs = account ? account.can_act_as || account.is_dev : openMode;
  const shown = me ?? account;

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-sm text-white/85 transition-colors hover:bg-white/10",
          actingAsOther ? "border-[var(--mtv-gold)]/60 bg-[var(--mtv-gold)]/10" : "border-white/15 bg-white/5"
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        title={actingAsOther ? `Signed in as ${account?.username}, acting as ${me?.username}` : undefined}
      >
        <Avatar user={shown} />
        {!compact && <span className="max-w-[9rem] truncate">{shown ? shown.username : "Choose user"}</span>}
        <ChevronDown className="h-3.5 w-3.5 opacity-70" />
      </button>

      {open && (
        <div
          className={cn(
            "absolute z-[70] rounded-xl border border-white/10 bg-black/90 p-2 shadow-2xl backdrop-blur-xl",
            up ? "bottom-full left-0 mb-2 w-52" : "right-0 mt-2 w-64"
          )}
          role="menu"
        >
          {account ? (
            <div className="px-2 pb-2">
              <p className="truncate text-sm font-semibold text-white">{account.username}</p>
              <p className="truncate text-xs text-white/50">
                {account.email}
                {account.is_dev && <span className="ml-1.5 rounded bg-[var(--mtv-gold)]/20 px-1 text-[10px] font-bold text-[var(--mtv-gold)]">DEV</span>}
              </p>
            </div>
          ) : (
            <p className="px-2 pb-2 text-xs text-white/50">Testing mode: pick any user, no sign-in needed.</p>
          )}
          {canActAs && <ActAs account={account} me={me} onDone={() => setOpen(false)} />}
          {account ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                void signOut();
              }}
              className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-white/10 px-2 py-2 text-left text-sm text-white/75 hover:bg-white/10"
            >
              <LogOut className="h-4 w-4" />
              Log out
            </button>
          ) : (
            <Link
              href={loginHref}
              onClick={() => setOpen(false)}
              className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-white/10 px-2 py-2 text-left text-sm text-white/75 hover:bg-white/10"
            >
              <LogIn className="h-4 w-4" />
              Sign in or create an account
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

/** Pick any user (or make a demo one) to act as. */
function ActAs({ account, me, onDone }: { account: MeOut | null; me: UserOut | null; onDone: () => void }) {
  const [users, setUsers] = useState<UserOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    fetchUsers()
      .then(setUsers)
      .catch((e: Error) => setError(e.message));
  }, []);

  const choose = (user: UserOut) => {
    setCurrentUser(user);
    onDone();
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
    <div className="border-t border-white/10 pt-2">
      <p className="px-2 pb-1.5 text-[11px] uppercase tracking-wider text-white/45">Act as</p>
      {!users && !error && (
        <div className="flex items-center gap-2 px-2 py-2 text-sm text-white/60">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading users…
        </div>
      )}
      <div className="max-h-56 overflow-y-auto" role="listbox">
        {users?.map((user) => (
          <button
            key={user.id}
            type="button"
            role="option"
            aria-selected={me?.id === user.id}
            onClick={() => choose(user)}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-white/85 hover:bg-white/10"
          >
            <Avatar user={user} className="text-white/50" />
            <span className="flex-1 truncate">
              {user.username}
              {user.id === account?.id && <span className="text-white/40"> (you)</span>}
            </span>
            {me?.id === user.id && <Check className="h-4 w-4 text-[var(--mtv-gold)]" />}
          </button>
        ))}
      </div>
      <div className="mt-2 flex gap-1.5">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void create()}
          placeholder="New demo user"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-white placeholder:text-white/35 focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void create()}
          disabled={creating || !newName.trim()}
          className="rounded-lg bg-[var(--mtv-gold)] px-2 text-[var(--mtv-on-gold)] disabled:opacity-40"
          aria-label="Create demo user"
        >
          {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        </button>
      </div>
      {error && <p className="px-2 pt-1.5 text-xs text-[var(--mtv-red)]">{error}</p>}
      {account && me && me.id !== account.id && (
        <button
          type="button"
          onClick={() => choose(account)}
          className="mt-1 w-full rounded-lg px-2 py-1.5 text-left text-xs text-white/50 hover:bg-white/10"
        >
          Back to {account.username}
        </button>
      )}
    </div>
  );
}

/** Shown in place of owner-only content when nobody is signed in or picked. */
export function ChooseUserNotice({ action }: { action: string }) {
  const loginHref = useLoginHref();
  const openMode = useActAsOpen();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-[var(--mtv-divider)] p-4 text-sm text-[var(--mtv-text-2)]">
      <span>{openMode ? `Pick a user or sign in to ${action}.` : `Sign in to ${action}.`}</span>
      <div className="flex items-center gap-2">
        {openMode && <UserSwitcher />}
        <Link
          href={loginHref}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--mtv-gold)] px-3 py-1.5 text-[13px] font-semibold text-[var(--mtv-on-gold)]"
        >
          <LogIn className="h-3.5 w-3.5" />
          Sign in
        </Link>
      </div>
    </div>
  );
}
