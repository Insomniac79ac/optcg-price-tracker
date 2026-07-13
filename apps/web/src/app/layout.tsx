import type { Metadata } from "next";
import "./globals.css";

import { AuthSessionProvider } from "@/components/AuthSessionProvider";

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
    <html lang="en" className="dark">
      <body className="min-h-screen bg-neutral-950 font-sans text-neutral-100 antialiased">
        <AuthSessionProvider>{children}</AuthSessionProvider>
      </body>
    </html>
  );
}
