"use client";

/**
 * MinedIt landing page.
 *
 * The sunrise hero, a grayscale games strip, a bold statement (no boxed
 * search-preview cards; those read as generic SaaS filler and were pulled
 * out entirely; real search lives on /explore and /library), and a closing
 * call to action into the real application.
 */

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, Clock, Layers, Search, Upload } from "lucide-react";

import { Footer } from "@/components/footer";
import { GameMarquee } from "@/components/hero/game-marquee";
import { MinecraftSunriseHero } from "@/components/hero/minecraft-sunrise-hero";
import { SiteNav } from "@/components/hero/site-nav";

const RISE = {
  initial: { opacity: 0, y: 26 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, amount: 0.4 },
};

const CAPABILITIES = [
  {
    icon: Search,
    title: "Natural language, not filenames",
    body: "Describe the moment the way you'd describe it to a friend. Retrieval blends visual similarity, transcript meaning and keyword matching.",
  },
  {
    icon: Clock,
    title: "Timestamps, not whole videos",
    body: "Every result is a moment with a start and end. Clicking one opens the player already seeked to it.",
  },
  {
    icon: Layers,
    title: "Evidence you can inspect",
    body: "Each result shows which signals fired, their raw scores and why it landed in its match-strength bucket.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#07090f] text-white">
      <SiteNav />

      {/* ── 1 + 2: hero and scroll-driven sunrise ── */}
      <MinecraftSunriseHero
        imageSrc="/images/minecraft-hero.webp"
        headline="Your moments. Rediscovered."
        subhead="Search every clip. Find every moment."
        wordmark="MinedIt"
      />

      {/* ── games strip ── */}
      <GameMarquee />

      {/* ── 3: bold statement, no boxed search UI ── */}
      <section className="relative mx-auto max-w-6xl px-6 py-24 sm:py-32">
        <motion.div {...RISE} transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}>
          <h2 className="font-display max-w-3xl text-balance text-5xl uppercase leading-[0.95] tracking-tight sm:text-7xl">
            Every clip <span className="text-[var(--mtv-gold)]">has a story.</span>
            <br />
            Find yours.
          </h2>
          <p className="mt-6 max-w-xl text-base text-white/55 sm:text-xl">
            Search your gaming moments with natural language. No filenames, no scrubbing.
          </p>
        </motion.div>

        <div className="mt-20 grid gap-8 sm:grid-cols-3">
          {CAPABILITIES.map((capability, index) => (
            <motion.div
              key={capability.title}
              {...RISE}
              transition={{
                duration: 0.6,
                delay: index * 0.09,
                ease: [0.22, 1, 0.36, 1],
              }}
            >
              <capability.icon className="mb-3 h-5 w-5 text-white/40" />
              <h3 className="text-sm font-semibold">{capability.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-white/50">{capability.body}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── closing call to action ── */}
      <section className="relative overflow-hidden border-t border-white/5">
        <div
          className="pointer-events-none absolute inset-0 opacity-60"
          style={{
            background:
              "radial-gradient(ellipse at 50% 120%, rgba(203,255,61,0.14) 0%, rgba(203,255,61,0.04) 40%, rgba(0,0,0,0) 70%)",
          }}
        />
        <motion.div
          {...RISE}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="relative mx-auto flex max-w-3xl flex-col items-center px-6 py-24 text-center sm:py-32"
        >
          <h2 className="text-balance text-4xl font-extrabold tracking-tight sm:text-5xl">
            Start mining your footage.
          </h2>
          <p className="mt-4 max-w-md text-sm text-white/55 sm:text-lg">
            Index a clip once, then find any moment in it for as long as you keep it.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/library"
              className="group inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--mtv-gold)] px-6 py-3 text-sm font-bold text-[var(--mtv-on-gold)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--mtv-gold)]"
            >
              Explore Library
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link
              href="/upload"
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/[0.04] px-6 py-3 text-sm font-medium text-white backdrop-blur-sm transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
            >
              <Upload className="h-4 w-4" />
              Upload a Clip
            </Link>
          </div>
        </motion.div>
      </section>

      <Footer />
    </div>
  );
}
