"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";

import { ActionButton } from "@/components/ui/ActionButton";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";

const ADMIN_CREDENTIALS_PROVIDER_ID = "admin-credentials";

// Every failure - unknown email, wrong password, throttled, disabled,
// network error - renders identically. Distinguishing them here would
// undo the backend's deliberately generic /auth/admin/verify responses
// (see services/api/app/api/admin_login.py's module docstring).
const GENERIC_ERROR = "Invalid email or password.";

/** Client boundary for the one bit of /admin/login that needs
 * next-auth/react - the parent page is a Server Component so it can check
 * isAdminLoginEnabled() and an existing admin session without shipping
 * anything sensitive to the browser. `callbackUrl` has already been
 * validated by the parent (src/lib/callbackUrl.ts). Uses signIn(...,
 * { redirect: false }) so a failed attempt can show GENERIC_ERROR in place
 * rather than round-tripping through a NextAuth error page. */
export function AdminLoginForm({ callbackUrl }: { callbackUrl: string }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await signIn(ADMIN_CREDENTIALS_PROVIDER_ID, {
        email,
        password,
        redirect: false,
      });
      if (!result || result.error) {
        setError(GENERIC_ERROR);
        return;
      }
      router.push(callbackUrl);
      router.refresh();
    } catch {
      setError(GENERIC_ERROR);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <label className="flex flex-col gap-1 text-xs text-text-secondary">
        Email
        <input
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={FILTER_INPUT_CLASS}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-text-secondary">
        Password
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={FILTER_INPUT_CLASS}
        />
      </label>

      {error && (
        <div className="rounded-control border border-signal-red/40 bg-signal-red/10 px-3 py-2 text-xs text-signal-red">
          {error}
        </div>
      )}

      <ActionButton type="submit" variant="primary" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </ActionButton>
    </form>
  );
}
