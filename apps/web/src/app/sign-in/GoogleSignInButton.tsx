"use client";

import { signIn } from "next-auth/react";

import { ActionButton } from "@/components/ui/ActionButton";
import { trackEvent } from "@/lib/analytics";

/** Client boundary for the one bit of this page that needs next-auth/react
 * - the parent page is a Server Component so it can read process.env
 * (whether Google OAuth is actually configured) without ever shipping the
 * values themselves to the browser. `callbackUrl` has already been
 * validated by the parent (see src/lib/callbackUrl.ts) before it reaches
 * here. */
export function GoogleSignInButton({ callbackUrl }: { callbackUrl: string }) {
  return (
    <ActionButton variant="primary" className="min-h-11 px-4 text-sm font-semibold md:min-h-9" onClick={() => {
        trackEvent("sign_in_started", { page_type: "sign_in" });
        void signIn("google", { callbackUrl });
      }}>
      Sign in with Google
    </ActionButton>
  );
}
