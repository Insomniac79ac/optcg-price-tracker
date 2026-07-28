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
      {/* lg:pl-56 clears AppShell's fixed sidebar (see components/ui/AppShell.tsx) -
          set here once rather than in every page so no page.tsx needs to change.
          Sidebar only becomes a fixed, always-visible rail at the `lg` (1024px)
          breakpoint - below that (including tablet/768px) it stays a drawer so
          content gets the full viewport width. */}
      <body className="flex min-h-screen flex-col bg-bg-page font-sans text-text-primary antialiased lg:pl-56">
        <AuthSessionProvider>
          <div className="flex-1">{children}</div>
          <Footer />
        </AuthSessionProvider>
      </body>
    </html>
  );
}
