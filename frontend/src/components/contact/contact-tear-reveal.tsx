"use client";

/**
 * Closing "Contact us" section: the MinedTV wordmark tears open like a film
 * clapperboard snapping shut, in the spirit of the tiger-tear-reveal
 * reference but scoped down to a one-shot in-view animation (no scroll
 * scrubbing) and restyled gold-on-dark for MinedTV — no tiger artwork, no
 * borrowed branding.
 *
 * Two clapperboard bars start pressed together over the wordmark, then snap
 * apart; the wordmark itself splits into top/bottom halves via clip-path and
 * tears away with them, revealing the contact panel underneath.
 */

import { motion } from "framer-motion";
import { Mail } from "lucide-react";

const EASE = [0.16, 1, 0.3, 1] as const;

export function ContactTearReveal({
  wordmark = "MinedTV",
  email = "hello@minedtv.app",
}: {
  wordmark?: string;
  email?: string;
}) {
  return (
    <section className="relative overflow-hidden bg-[#07090f] py-28 sm:py-36">
      <div className="mx-auto flex max-w-3xl flex-col items-center px-6 text-center">
        <motion.p
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, amount: 0.6 }}
          transition={{ duration: 0.4 }}
          className="mb-8 text-[11px] font-semibold uppercase tracking-[0.42em] text-white/50"
        >
          Contact us
        </motion.p>

        <div className="relative isolate h-[14vw] max-h-32 min-h-20 w-full">
          {/* clapperboard bars — pressed together, then snap to the edges */}
          <motion.div
            initial={{ y: 0 }}
            whileInView={{ y: "-130%" }}
            viewport={{ once: true, amount: 0.6 }}
            transition={{ duration: 0.38, delay: 0.15, ease: EASE }}
            className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-[var(--mtv-gold)]"
          />
          <motion.div
            initial={{ y: 0 }}
            whileInView={{ y: "130%" }}
            viewport={{ once: true, amount: 0.6 }}
            transition={{ duration: 0.38, delay: 0.15, ease: EASE }}
            className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-[var(--mtv-gold)]"
          />

          {/* wordmark, torn in half */}
          <motion.span
            aria-hidden
            initial={{ y: 0, rotate: 0 }}
            whileInView={{ y: "-60%", rotate: -3 }}
            viewport={{ once: true, amount: 0.6 }}
            transition={{ duration: 0.5, delay: 0.2, ease: EASE }}
            style={{ clipPath: "inset(0 0 50% 0)" }}
            className="absolute inset-0 flex items-center justify-center select-none whitespace-nowrap text-[13vw] font-black leading-none text-white"
          >
            {wordmark}
          </motion.span>
          <motion.span
            aria-hidden
            initial={{ y: 0, rotate: 0 }}
            whileInView={{ y: "60%", rotate: 3 }}
            viewport={{ once: true, amount: 0.6 }}
            transition={{ duration: 0.5, delay: 0.2, ease: EASE }}
            style={{ clipPath: "inset(50% 0 0 0)" }}
            className="absolute inset-0 flex items-center justify-center select-none whitespace-nowrap text-[13vw] font-black leading-none text-white"
          >
            {wordmark}
          </motion.span>

          <h2 className="sr-only">{wordmark}</h2>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.6 }}
          transition={{ duration: 0.5, delay: 0.55, ease: EASE }}
          className="mt-10 flex flex-col items-center gap-4"
        >
          <p className="max-w-md text-sm text-white/55 sm:text-base">
            Judging, feedback, or just want to talk clips — we&apos;re here.
          </p>
          <a
            href={`mailto:${email}`}
            className="group inline-flex items-center gap-2 rounded-xl bg-[var(--mtv-gold)] px-6 py-3 text-sm font-bold text-[var(--mtv-on-gold)] transition-opacity hover:opacity-90"
          >
            <Mail className="h-4 w-4" />
            {email}
          </a>
        </motion.div>
      </div>
    </section>
  );
}
