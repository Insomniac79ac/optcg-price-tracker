import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

import { AuthSessionProvider } from "@/components/AuthSessionProvider";

// Self-hosted at build time by next/font (no runtime request to Google
// Fonts, so this doesn't need a CSP font-src allowance). display: "swap"
// means a missing/slow weight just falls back to the --font-sans/--font-mono
// system stack in globals.css rather than blocking render.
const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-ibm-plex-sans",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OPTCG Price Tracker",
  description: "Price tracking dashboard for One Piece Card Game listings",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${ibmPlexSans.variable} ${ibmPlexMono.variable}`}>
      {/* md:pl-56 clears AppShell's fixed sidebar (see components/ui/AppShell.tsx) -
          set here once rather than in every page so no page.tsx needs to change. */}
      <body className="min-h-screen bg-bg-page font-sans text-text-primary antialiased md:pl-56">
        <AuthSessionProvider>{children}</AuthSessionProvider>
      </body>
    </html>
  );
}
