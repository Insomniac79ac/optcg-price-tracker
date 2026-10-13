import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

import { AuthSessionProvider } from "@/components/AuthSessionProvider";
import { Footer } from "@/components/Footer";
import { JsonLd } from "@/components/JsonLd";
import { publicSiteUrl } from "@/lib/publicRoutes";
import { absoluteUrl } from "@/lib/publicSeo";
import { brand } from "@/lib/brand";

// All three families are committed under ./fonts and served by next/font/local
// - no build-time or runtime request to Google Fonts, so neither the Vercel
// build nor CSP font-src depends on it (see fonts/README.md for provenance).
// display: "swap" means a missing/slow weight just falls back to the
// --font-sans/--font-display/--font-mono system stack in globals.css rather
// than blocking render - see docs/brand.md "Typography".
const manrope = localFont({
  src: "./fonts/Manrope-Variable.ttf",
  weight: "400 700",
  variable: "--font-manrope",
  display: "swap",
});

// Fraunces and IBM Plex Mono are the latin-subset files Google Fonts served to
// next/font/google, committed unmodified, so they render exactly as before.
const fraunces = localFont({
  src: "./fonts/Fraunces-latin.woff2",
  weight: "500 700",
  variable: "--font-fraunces",
  display: "swap",
  adjustFontFallback: "Times New Roman",
});

const ibmPlexMono = localFont({
  src: [
    { path: "./fonts/IBMPlexMono-Regular-latin.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexMono-Medium-latin.woff2", weight: "500", style: "normal" },
    { path: "./fonts/IBMPlexMono-SemiBold-latin.woff2", weight: "600", style: "normal" },
  ],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(publicSiteUrl()),
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
        <JsonLd data={{ "@context": "https://schema.org", "@graph": [{ "@type": "WebSite", "@id": absoluteUrl("/#website"), url: absoluteUrl("/"), name: brand.productName, description: brand.metadataDescription }, { "@type": "Organization", "@id": absoluteUrl("/#organization"), name: brand.productName, url: absoluteUrl("/"), description: "Independent One Piece card price tracking tool." }] }} />
        <AuthSessionProvider>
          <div className="flex-1">{children}</div>
          <Footer />
        </AuthSessionProvider>
      </body>
    </html>
  );
}
