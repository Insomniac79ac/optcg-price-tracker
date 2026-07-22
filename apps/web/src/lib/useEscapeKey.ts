"use client";

import { useEffect } from "react";

/** Closes a modal on Esc while it's open. CommandPalette/KeyboardShortcutsModal
 * already get this for free from AppShell's global key handler; standalone
 * modals (ConfirmActionModal, SaveViewModal, ManageSavedViewsModal, ...) that
 * can be opened from any page need their own listener. */
export function useEscapeKey(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);
}
