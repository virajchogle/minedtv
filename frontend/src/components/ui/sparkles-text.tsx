"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface Sparkle {
  id: string;
  x: string;
  y: string;
  color: string;
  size: number;
  createdAt: number;
}

const LIFETIME_MS = 800;
const rand = (min: number, max: number) => Math.random() * (max - min) + min;
const uid = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;

function Star({ size, color }: { size: number; color: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 68 68"
      fill="none"
    >
      <path
        d="M26.5 25.5C19.0043 33.3697 0 34 0 34C0 34 19.1013 35.3684 26.5 43.5C33.234 50.901 34 68 34 68C34 68 36.9181 50.351 44.5 43.5C51.6979 36.9592 68 34 68 34C68 34 51.6979 31.0408 44.5 24.5C36.9181 17.649 34 0 34 0C34 0 33.1747 17.9994 26.5 25.5Z"
        fill={color}
      />
    </svg>
  );
}

export function SparklesText({
  text,
  className,
  colors = { first: "#003998", second: "#4d7fff" },
  sparklesCount = 8,
}: {
  text: string;
  className?: string;
  colors?: { first: string; second: string };
  sparklesCount?: number;
}) {
  const [sparkles, setSparkles] = useState<Sparkle[]>([]);

  const make = useCallback(
    (): Sparkle => ({
      id: uid(),
      x: `${rand(-5, 105)}%`,
      y: `${rand(-15, 115)}%`,
      color: Math.random() > 0.5 ? colors.first : colors.second,
      size: rand(8, 18),
      createdAt: Date.now(),
    }),
    [colors.first, colors.second]
  );

  useEffect(() => {
    setSparkles(Array.from({ length: sparklesCount }, make));
    const id = setInterval(() => {
      const now = Date.now();
      setSparkles((prev) => [
        ...prev.filter((s) => now - s.createdAt < LIFETIME_MS),
        make(),
      ]);
    }, 350);
    return () => clearInterval(id);
  }, [sparklesCount, make]);

  return (
    <span className={cn("relative inline-block", className)}>
      {sparkles.map((s) => (
        <span
          key={s.id}
          className="absolute pointer-events-none select-none"
          style={{
            left: s.x,
            top: s.y,
            transform: "translate(-50%, -50%)",
            zIndex: 1,
            animation: `sparkle-pop ${LIFETIME_MS}ms ease-in-out forwards`,
          }}
        >
          <Star size={s.size} color={s.color} />
        </span>
      ))}
      <strong className="relative font-bold" style={{ zIndex: 2 }}>
        {text}
      </strong>
    </span>
  );
}
