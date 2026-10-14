"use client";

import { signOut } from "next-auth/react";
import { useState } from "react";

import { ActionButton } from "@/components/ui/ActionButton";

export const DELETE_CONFIRMATION = "delete my account";

const BUTTON_SIZE = "min-h-11 px-4 text-sm md:min-h-9";

/** Typed confirmation, then DELETE /api/me (same-origin; the server mints the
 * API token and refuses cross-site requests). On success the session is
 * ended and the visitor lands on the homepage. */
export function DeleteAccount() {
  const [typed, setTyped] = useState("");
  const [state, setState] = useState<"idle" | "deleting" | "failed">("idle");
  const confirmed = typed.trim().toLowerCase() === DELETE_CONFIRMATION;

  async function deleteAccount() {
    if (!confirmed) return;
    setState("deleting");
    try {
      const response = await fetch(`/api/me?confirm=${encodeURIComponent(DELETE_CONFIRMATION)}`, {
        method: "DELETE",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (response.status !== 204) {
        setState("failed");
        return;
      }
      await signOut({ callbackUrl: "/" });
    } catch {
      setState("failed");
    }
  }

  return (
    <div className="space-y-3">
      <label htmlFor="delete-confirmation" className="block text-sm leading-6 text-text-secondary">
        Type <span className="font-mono text-text-primary">{DELETE_CONFIRMATION}</span> to confirm.
      </label>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          id="delete-confirmation"
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          className="min-h-11 w-full rounded-control border border-border-default bg-transparent px-3 text-sm text-text-primary placeholder:text-text-faint focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 sm:max-w-xs md:min-h-9"
        />
        <ActionButton variant="danger" className={BUTTON_SIZE} disabled={!confirmed || state === "deleting"} onClick={deleteAccount}>
          {state === "deleting" ? "Deleting…" : "Delete my account"}
        </ActionButton>
      </div>
      {state === "failed" && (
        <p role="alert" className="text-sm text-signal-red">
          Your account was not deleted. Please try again in a moment.
        </p>
      )}
    </div>
  );
}

export function SignOutButton() {
  return (
    <ActionButton className={BUTTON_SIZE} onClick={() => signOut({ callbackUrl: "/" })}>
      Sign out
    </ActionButton>
  );
}
