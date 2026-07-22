"use client";

import { clearAdminToken } from "@/lib/api";
import { ActionButton } from "@/components/ui/ActionButton";

export function AdminLogoutButton() {
  return (
    <ActionButton
      variant="default"
      onClick={() => {
        clearAdminToken();
        window.location.reload();
      }}
    >
      Clear admin token
    </ActionButton>
  );
}
