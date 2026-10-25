"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, Home, Library, Upload, Settings, Video } from "lucide-react";
import { UserSwitcher } from "@/components/current-user";
import { cn } from "@/lib/utils";

const navItems = [
  { icon: Home,      label: "Home",    href: "/" },
  { icon: Library,   label: "Library", href: "/library" },
  { icon: Upload,    label: "Upload",  href: "/upload" },
  { icon: Compass,   label: "Explore", href: "/explore" },
];

export function Sidebar() {
  const pathname  = usePathname();
  const [expanded, setExpanded] = useState(false);

  // Text fades in after width starts expanding (150ms delay),
  // fades out immediately when collapsing.
  const textStyle: React.CSSProperties = {
    opacity:    expanded ? 1 : 0,
    transition: `opacity 200ms ease ${expanded ? "150ms" : "0ms"}`,
    whiteSpace: "nowrap",
    overflow:   "hidden",
  };

  return (
    <div
      className="fixed left-0 top-0 h-screen z-40 flex flex-col justify-between overflow-hidden py-4"
      style={{
        width:               expanded ? "220px" : "64px",
        transition:          "width 250ms ease",
        opacity:             expanded ? 1 : 0.7,
        background:          expanded ? "rgba(0, 8, 20, 0.8)" : "rgba(0, 8, 20, 0.6)",
        backdropFilter:      "blur(16px)",
        WebkitBackdropFilter:"blur(16px)",
        borderRight:         "1px solid rgba(255, 255, 255, 0.06)",
      }}
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
    >

      {/* ── Top: logo + primary nav ───────────────────────────────────── */}
      <div>
        {/* Logo row */}
        <div className="flex items-center h-12 px-4 mb-4">
          <div className="shrink-0 p-2 bg-primary rounded-lg">
            <Video className="w-5 h-5 text-white" />
          </div>
          <span className="ml-3 font-bold text-xl text-white" style={textStyle}>
            MineDTV
          </span>
        </div>

        {/* Nav items */}
        <nav className="flex flex-col gap-1 px-2">
          {navItems.map(({ icon: Icon, label, href }) => {
            const isActive = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center h-10 px-3 rounded-lg transition-colors duration-200",
                  isActive
                    ? "bg-white/15 text-white"
                    : "text-white hover:bg-white/10"
                )}
              >
                <Icon className="w-5 h-5 shrink-0" />
                <span className="ml-3 text-sm font-medium" style={textStyle}>
                  {label}
                </span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* ── Bottom: greeting + settings + logout ─────────────────────── */}
      <div className="flex flex-col gap-1 px-2">
        <div className="px-1 pb-1" style={textStyle}>
          <UserSwitcher />
        </div>

        <Link
          href="/settings"
          className={cn(
            "flex items-center h-10 px-3 rounded-lg transition-colors duration-200",
            pathname === "/settings"
              ? "bg-white/15 text-white"
              : "text-white hover:bg-white/10"
          )}
        >
          <Settings className="w-5 h-5 shrink-0" />
          <span className="ml-3 text-sm font-medium" style={textStyle}>
            Settings
          </span>
        </Link>

      </div>

    </div>
  );
}
