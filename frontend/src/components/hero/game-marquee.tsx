"use client";

/**
 * Horizontal grayscale wordmark strip, same idea as medal.tv's supported-games
 * band under their hero. These are stylized text treatments approximating
 * each game's native type feel (condensed/italic/blocky/etc.), not actual
 * logo artwork, since reproducing trademarked logos isn't something to do
 * without the rights holder's assets.
 */

import { Marquee } from "@/components/ui/marquee";

const GAMES: { name: string; className: string }[] = [
  { name: "FORTNITE", className: "italic skew-x-[-6deg] tracking-tight" },
  { name: "VALORANT", className: "tracking-[0.15em]" },
  { name: "MINECRAFT", className: "font-mono tracking-tight" },
  { name: "LEAGUE OF LEGENDS", className: "tracking-wide" },
  { name: "APEX LEGENDS", className: "italic tracking-tight" },
  { name: "CALL OF DUTY", className: "tracking-[0.1em]" },
  { name: "ROCKET LEAGUE", className: "italic skew-x-[-4deg]" },
  { name: "OVERWATCH 2", className: "tracking-wide" },
];

export function GameMarquee() {
  return (
    <div className="border-y border-white/5 bg-[#07090f] py-5">
      <Marquee pauseOnHover repeat={3} className="[--duration:32s] [--gap:3.5rem]">
        {GAMES.map((game) => (
          <span
            key={game.name}
            className={`shrink-0 whitespace-nowrap text-2xl font-extrabold uppercase text-white/35 transition-colors hover:text-white ${game.className}`}
          >
            {game.name}
          </span>
        ))}
      </Marquee>
    </div>
  );
}
