import type { Metadata } from "next";
import { Archivo_Black, Geist, Geist_Mono, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import { BackgroundEffects } from "@/components/background-effects";
import { Splash } from "@/components/splash";
import Velaris from "@/components/ui/velaris";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Bold display stack for the homepage headline treatment, the game marquee
// and the footer — same fonts as the portfolio reference you gave for the
// footer's typography.
const archivoBlack = Archivo_Black({
  weight: "400",
  variable: "--font-archivo-black",
  subsets: ["latin"],
});

const spaceGrotesk = Space_Grotesk({
  weight: ["500", "700"],
  variable: "--font-space-grotesk",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  weight: ["400", "500", "700"],
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MinedIt",
  description: "Semantic video moment retrieval across a gallery or within a single video",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('minedtv-theme');document.documentElement.classList.toggle('dark',t!=='light')}catch(e){document.documentElement.classList.add('dark')}`,
          }}
        />
        {/* The launch splash plays once per browser session; later page loads hide it before paint. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{if(sessionStorage.getItem('mtv-splash'))document.documentElement.classList.add('mtv-splash-seen');else sessionStorage.setItem('mtv-splash','1')}catch(e){}`,
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${archivoBlack.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable} antialiased text-foreground`}
      >
        <Splash />
        <script
          dangerouslySetInnerHTML={{
            __html: `document.querySelector('.mtv-splash')?.addEventListener('click',function(e){e.currentTarget.remove()})`,
          }}
        />
        <BackgroundEffects />
        <Velaris height="100%" className="fixed inset-0 -z-10 opacity-70" />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
