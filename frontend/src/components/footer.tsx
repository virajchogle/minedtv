"use client";

/**
 * Site footer. Not the DoodleCrewFooter component you referenced — only a
 * demo wrapper (`<DoodleCrewFooter />`, no props, no source) was supplied for
 * that one, so there's nothing to port faithfully. This reuses the type
 * system from the portfolio-site CSS you pasted instead: Archivo Black for
 * the oversized wordmark, JetBrains Mono for the meta row, same black/lime
 * MinedIt palette as the rest of the app.
 */

import Link from "next/link";

const LINKS = [
  { label: "Home", href: "/" },
  { label: "Explore", href: "/explore" },
  { label: "My Library", href: "/library" },
  { label: "Upload", href: "/upload" },
];

export function Footer() {
  return (
    <footer className="border-t border-white/5 bg-[#050505]">
      <div className="mx-auto max-w-6xl px-6 py-16">
        <p className="font-display select-none text-[18vw] leading-[0.8] tracking-tight text-white/95 sm:text-[11vw]">
          Mined<span className="text-[var(--mtv-gold)]">It</span>
        </p>

        <div className="mt-10 flex flex-col items-start justify-between gap-8 border-t border-white/10 pt-8 sm:flex-row sm:items-end">
          <nav className="flex flex-wrap gap-x-6 gap-y-2 font-mono text-xs uppercase tracking-[0.15em] text-white/50">
            {LINKS.map((link) => (
              <Link key={link.href} href={link.href} className="transition-colors hover:text-[var(--mtv-gold)]">
                {link.label}
              </Link>
            ))}
          </nav>
          <p className="font-mono text-xs text-white/30">
            © {new Date().getFullYear()} MinedIt — semantic video moment retrieval.
          </p>
        </div>
      </div>
    </footer>
  );
}
