"use client";

/** Sign in or create an account, then return to ?next (default: My Library). */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, Loader2, LogOut } from "lucide-react";

import { useAccount } from "@/components/current-user";
import { SiteNav } from "@/components/hero/site-nav";
import { signIn, signOut, signUp } from "@/lib/api";
import { usePageTitle } from "@/lib/use-page-title";
import { cn } from "@/lib/utils";

type Mode = "signin" | "signup";

export default function LoginPage() {
  usePageTitle("Sign in");
  return (
    <div className="min-h-screen px-4 pb-16 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />
      <main id="main-content">
        <Suspense>
          <LoginForm />
        </Suspense>
      </main>
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const account = useAccount();
  const [mode, setMode] = useState<Mode>("signin");
  const [login, setLogin] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only same-site paths, so ?next can't bounce someone to another site.
  const nextParam = params.get("next");
  const next = nextParam && nextParam.startsWith("/") && !nextParam.startsWith("//") ? nextParam : "/library";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") await signIn(login.trim(), password);
      else await signUp(username.trim(), email.trim(), password, birthDate);
      router.push(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  if (account) {
    return (
      <div className="mx-auto max-w-sm space-y-4 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-6">
        <h1 className="text-xl font-semibold">You&apos;re signed in</h1>
        <p className="text-sm text-[var(--mtv-text-2)]">
          as <span className="font-semibold text-[var(--mtv-text)]">{account.username}</span>
          {account.email && <> ({account.email})</>}
          {account.is_dev && ", a dev account: use the menu in the nav to act as any user"}.
        </p>
        <div className="flex gap-2">
          <Link
            href={next}
            className="rounded-lg bg-[var(--mtv-gold)] px-3 py-1.5 text-[13px] font-semibold text-[var(--mtv-on-gold)]"
          >
            Continue
          </Link>
          <button
            type="button"
            onClick={() => void signOut()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--mtv-divider)] px-3 py-1.5 text-[13px] font-semibold hover:bg-[var(--mtv-surface-high)]"
          >
            <LogOut className="h-3.5 w-3.5" /> Log out
          </button>
        </div>
      </div>
    );
  }

  const input =
    "block w-full rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-3 py-2 text-sm text-[var(--mtv-text)] placeholder:text-[var(--mtv-text-2)]/60 focus:border-[var(--mtv-gold)]/60 focus:outline-none";

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="mx-auto max-w-sm space-y-5 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-6"
    >
      {/* No visible heading in this design, but every page needs exactly one h1. */}
      <h1 className="sr-only">{mode === "signin" ? "Sign in" : "Create an account"}</h1>
      <div className="grid grid-cols-2 gap-1 rounded-xl bg-[var(--mtv-surface-high)] p-1 text-sm font-semibold">
        {(["signin", "signup"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => {
              setMode(m);
              setError(null);
            }}
            className={cn(
              "rounded-lg py-1.5 transition-colors",
              mode === m ? "bg-[var(--mtv-gold)] text-[var(--mtv-on-gold)]" : "text-[var(--mtv-text-2)] hover:text-[var(--mtv-text)]"
            )}
          >
            {m === "signin" ? "Sign in" : "Create account"}
          </button>
        ))}
      </div>

      {mode === "signin" ? (
        <label className="block space-y-1 text-xs text-[var(--mtv-text-2)]">
          Username or email
          <input value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" required className={input} />
        </label>
      ) : (
        <>
          <label className="block space-y-1 text-xs text-[var(--mtv-text-2)]">
            Username
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              minLength={2}
              maxLength={64}
              pattern="[A-Za-z0-9_.\-]+"
              title="Letters, numbers, dots, dashes or underscores"
              className={input}
            />
          </label>
          <label className="block space-y-1 text-xs text-[var(--mtv-text-2)]">
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required className={input} />
          </label>
          <label className="block space-y-1 text-xs text-[var(--mtv-text-2)]">
            Date of birth
            <input
              type="date"
              value={birthDate}
              onChange={(e) => setBirthDate(e.target.value)}
              autoComplete="bday"
              required
              max={new Date().toISOString().slice(0, 10)}
              className={input}
            />
            <span className="block text-[11px] text-[var(--mtv-text-2)]/70">
              Content flagged 18+ by our moderation is only shown to accounts old enough to see it.
            </span>
          </label>
        </>
      )}
      <label className="block space-y-1 text-xs text-[var(--mtv-text-2)]">
        Password
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          required
          minLength={mode === "signup" ? 8 : 1}
          className={input}
        />
      </label>

      {error && (
        <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--mtv-red)]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--mtv-gold)] py-2 text-sm font-bold text-[var(--mtv-on-gold)] disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}
        {mode === "signin" ? "Sign in" : "Create account"}
      </button>
    </form>
  );
}
