"use client";

import { useState } from "react";

import { setAdminToken } from "@/lib/api";

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
    <div className="rounded-lg border border-amber-900/50 bg-amber-950/30 p-8 text-center">
      <p className="mb-3 text-sm text-amber-200">Admin token required.</p>
      <form onSubmit={submit} className="flex justify-center gap-2">
        <input
          type="password"
          autoFocus
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          placeholder="Admin token"
          className="w-64 rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm text-neutral-100 placeholder:text-neutral-600"
        />
        <button
          type="submit"
          className="rounded bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-900 hover:bg-white"
        >
          Save token
        </button>
      </form>
    </div>
  );
}
