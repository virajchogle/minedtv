"use client";

/**
 * Floating navigation for the landing page.
 *
 * Links point only at routes that exist.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";

import { Logo } from "@/components/brand";
import { UserSwitcher } from "@/components/current-user";
import { cn } from "@/lib/utils";

const LINKS = [
  { label: "Home", href: "/" },
  { label: "Explore", href: "/explore" },
  { label: "My Library", href: "/library" },
  { label: "Upload", href: "/upload" },
  { label: "Dashboard", href: "/dashboard" },
  { label: "Profile", href: "/profile" },
] as const;

export function SiteNav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close the mobile sheet on Escape. The sheet never locks body scroll.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="fixed inset-x-0 top-0 z-[60] flex justify-center px-4 pt-4">
      <nav
        className={cn(
          "flex w-full max-w-5xl items-center justify-between rounded-2xl border px-4 py-2.5 transition-all duration-500",
          scrolled
            ? "border-white/10 bg-black/55 shadow-[0_8px_40px_rgba(0,0,0,0.45)] backdrop-blur-xl"
            : "border-white/5 bg-black/20 backdrop-blur-md"
        )}
        aria-label="Primary"
      >
        <Link
          href="/"
          className="flex items-center gap-2 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
        >
          <Logo size={28} />
        </Link>

        <div className="hidden items-center gap-1 sm:flex">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="rounded-lg px-3 py-1.5 text-sm text-white/70 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
            >
              {link.label}
            </Link>
          ))}
          <UserSwitcher className="ml-2" />
        </div>

        <div className="flex items-center gap-2 sm:hidden">
        <UserSwitcher compact />
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="rounded-lg p-1.5 text-white/80 transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60 sm:hidden"
          aria-expanded={open}
          aria-label={open ? "Close menu" : "Open menu"}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
        </div>
      </nav>

      {open && (
        <div className="absolute inset-x-4 top-20 rounded-2xl border border-white/10 bg-black/80 p-2 backdrop-blur-xl sm:hidden">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setOpen(false)}
              className="block rounded-lg px-3 py-2.5 text-sm text-white/80 transition-colors hover:bg-white/10 hover:text-white"
            >
              {link.label}
            </Link>
          ))}
        </div>
      )}
    </header>
  );
}
