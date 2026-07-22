"use client";

import { useState } from "react";

import { setAdminToken } from "@/lib/api";
import { ActionButton } from "@/components/ui/ActionButton";
import { FILTER_INPUT_CLASS } from "@/components/ui/FilterBar";

/** The single admin-token entry point, shown by every /admin/* page when no
 * token is set or the last request came back unauthorized - keeping this
 * one component consistent keeps token UX consistent everywhere it's used
 * (design brief "Admin token UX consistency"). Never logs or persists the
 * token anywhere but localStorage via setAdminToken (see lib/api.ts). */
export function AdminAuthGate({ onTokenSaved }: { onTokenSaved: () => void }) {
  const [tokenInput, setTokenInput] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) return;
    setAdminToken(trimmed);
    onTokenSaved();
  }

  return (
    <div className="rounded-panel border border-signal-warning/40 bg-signal-warning/10 p-8 text-center">
      <p className="mb-3 text-sm text-signal-warning">
        Admin token required. Enter the token to continue.
      </p>
      <form onSubmit={submit} className="flex justify-center gap-2">
        <input
          type="password"
          autoFocus
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="Admin token"
          className={`w-64 ${FILTER_INPUT_CLASS}`}
        />
        <ActionButton type="submit" variant="primary">
          Save token
        </ActionButton>
      </form>
    </div>
  );
}
