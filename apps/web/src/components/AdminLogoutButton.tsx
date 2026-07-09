"use client";

import { clearAdminToken } from "@/lib/api";

export function AdminLogoutButton() {
  return (
    <button
      onClick={() => {
        clearAdminToken();
        window.location.reload();
      }}
      className="rounded px-2.5 py-1 text-xs font-medium text-neutral-500 ring-1 ring-inset ring-neutral-800 hover:text-neutral-100"
    >
      Clear admin token
    </button>
  );
}
