import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Manrope } from "next/font/google";
import "./globals.css";

import { AuthSessionProvider } from "@/components/AuthSessionProvider";
import { Footer } from "@/components/Footer";
import { brand } from "@/lib/brand";

// Self-hosted at build time by next/font (no runtime request to Google
// Fonts, so this doesn't need a CSP font-src allowance). display: "swap"
// means a missing/slow weight just falls back to the --font-sans/
// --font-display/--font-mono system stack in globals.css rather than
// blocking render - see docs/brand.md "Typography".
const manrope = Manrope({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-manrope",
  display: "swap",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-fraunces",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: brand.metadataTitleDefault,
    template: brand.metadataTitleTemplate,
  },
  description: brand.metadataDescription,
  openGraph: {
    title: brand.metadataTitleDefault,
    description: brand.socialSharingDescription,
    siteName: brand.productName,
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`dark ${manrope.variable} ${fraunces.variable} ${ibmPlexMono.variable}`}>
      {/* No unconditional sidebar padding here any more. The persistent rail
          is admin-only (see components/ui/AppShell.tsx), and globals.css
          applies the matching padding only when a rail is actually present,
          keyed off its `data-app-rail` attribute - so the public collector
          pages get the full viewport width at every breakpoint. */}
      <body className="flex min-h-screen flex-col bg-bg-page font-sans text-text-primary antialiased">
        <AuthSessionProvider>
          <div className="flex-1">{children}</div>
          <Footer />
        </AuthSessionProvider>
      </body>
    </html>
  );
}
