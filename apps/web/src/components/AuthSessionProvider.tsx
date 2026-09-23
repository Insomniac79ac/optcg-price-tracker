"use client";

import { SessionProvider } from "next-auth/react";

export function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  // Refresh presentation of the server-enforced role lifetime on idle tabs too.
  return <SessionProvider refetchInterval={60} refetchOnWindowFocus>{children}</SessionProvider>;
}
