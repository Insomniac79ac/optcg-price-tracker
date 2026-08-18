"use client";

import { useSession } from "next-auth/react";

const GENERAL_SHORTCUTS: { keys: string; description: string }[] = [
  { keys: "⌘K / Ctrl K", description: "Open the command palette" },
  { keys: "Esc", description: "Close the command palette or this dialog" },
  { keys: "/", description: "Open the card search (when nothing else is focused)" },
  { keys: "?", description: "Open this shortcuts reference" },
];

const GOTO_SHORTCUTS: { keys: string; description: string }[] = [
  { keys: "g c", description: "Go to My Collection" },
  { keys: "g v", description: "Go to Collection Vault" },
  { keys: "g w", description: "Go to Wishlist" },
];

/** Plain reference modal for keyboard shortcuts - opened from the topbar "?"
 * button (`lg`+ only) or the global "?" key. Same chrome as
 * ConfirmActionModal/CommandPalette.
 *
 * The goto sequences are listed only for a signed-in collector: every one of
 * them targets a collector-tier route (My Collection, Vault, Wishlist), so
 * advertising them to a signed-out visitor documents three shortcuts that can
 * only ever land them on the sign-in wall. The shortcuts themselves are
 * unchanged - AppShell still owns them - this is only about not printing a
 * reference to capability the reader does not have. */
export function KeyboardShortcutsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { status } = useSession();
  const showGotoShortcuts = status === "authenticated";

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Keyboard shortcuts"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[80vh] w-full max-w-md overflow-y-auto rounded-modal border border-border-default bg-bg-elevated p-5"
      >
        <div className="mb-3 flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold text-text-primary">Keyboard shortcuts</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-xs font-medium text-text-muted hover:text-text-primary"
          >
            Close
          </button>
        </div>

        <ShortcutList title="General" items={GENERAL_SHORTCUTS} />
        {showGotoShortcuts && (
          <ShortcutList title="Go to (press g then a key)" items={GOTO_SHORTCUTS} />
        )}
      </div>
    </div>
  );
}

function ShortcutList({
  title,
  items,
}: {
  title: string;
  items: { keys: string; description: string }[];
}) {
  return (
    <div className="mb-4">
      <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-text-secondary">
        {title}
      </div>
      <div className="space-y-1.5">
        {items.map((item) => (
          <div key={item.keys} className="flex items-center justify-between gap-3 text-sm">
            <span className="text-text-secondary">{item.description}</span>
            <span className="mono shrink-0 rounded border border-border-default px-1.5 py-0.5 text-[11px] text-text-faint">
              {item.keys}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
