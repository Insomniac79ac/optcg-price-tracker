"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { CollectionForm, WatchForm } from "@/components/ui/PrintCollectorActions";

import styles from "./Collection.module.css";

/** An "Edit" button that opens its form in a sheet: it rises from the bottom
 * on a phone and sits centred on a desktop. Escape, the backdrop and the
 * form's own Cancel close it; focus stays inside while it is open and returns
 * to the button afterwards. Shared by /collection and /watchlist. */
export function EditSheet({
  title,
  buttonLabel = "Edit",
  buttonDescription,
  children,
}: {
  title: string;
  buttonLabel?: string;
  /** Accessible name for the opener, e.g. "Edit Monkey.D.Luffy, OP05-119". */
  buttonDescription: string;
  /** The form; `close` dismisses the sheet, `done` dismisses it and refreshes
   * the page from the API so every number shown is the server's again. */
  children: (actions: { close: () => void; done: () => void }) => ReactNode;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const sheetRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sheetRef.current?.querySelector<HTMLInputElement>("input")?.focus();
    const opener = openerRef.current;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
      if (event.key !== "Tab" || !sheetRef.current) return;
      // Keep focus inside the sheet while it is open.
      const focusable = sheetRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input, a[href]");
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [open]);

  return (
    <>
      <button ref={openerRef} type="button" className={styles.editButton} onClick={() => setOpen(true)} aria-label={buttonDescription}>
        {buttonLabel}
      </button>
      {open && (
        <div className={styles.sheetBackdrop} onClick={(event) => event.target === event.currentTarget && setOpen(false)}>
          <div ref={sheetRef} className={styles.sheet} role="dialog" aria-modal="true" aria-labelledby={titleId}>
            <div className={styles.sheetHandle} aria-hidden="true" />
            <h2 id={titleId} className={styles.sheetTitle}>{title}</h2>
            {children({
              close: () => setOpen(false),
              done: () => {
                setOpen(false);
                router.refresh();
              },
            })}
          </div>
        </div>
      )}
    </>
  );
}

/** "Edit" on a /collection card: the shared collection form in an EditSheet. */
export function CollectionEditSheet({
  entryId,
  cardPrintId,
  versionLabel,
  quantity,
  paidJpyPerCard,
  acquiredOn,
  buttonLabel = "Edit",
  buttonDescription,
}: {
  entryId: number;
  cardPrintId: number | null;
  versionLabel: string;
  quantity: number;
  paidJpyPerCard: number | null;
  acquiredOn: string | null;
  buttonLabel?: string;
  /** Accessible name for the opener, e.g. "Edit Monkey.D.Luffy OP05-119". */
  buttonDescription: string;
}) {
  return (
    <EditSheet title="Edit in your collection" buttonLabel={buttonLabel} buttonDescription={buttonDescription}>
      {({ close, done }) => (
        <CollectionForm
          cardPrintId={cardPrintId}
          versionLabel={versionLabel}
          held={{ entryId, quantity, paidJpyPerCard, acquiredOn }}
          onCancel={close}
          onDone={done}
        />
      )}
    </EditSheet>
  );
}

/** "Edit" on a /watchlist row: the print page's watch form (target price,
 * stop watching) in an EditSheet. */
export function WatchEditSheet({
  entryId,
  cardPrintId,
  versionLabel,
  targetJpy,
  buttonDescription,
}: {
  entryId: number;
  cardPrintId: number | null;
  versionLabel: string;
  targetJpy: number | null;
  buttonDescription: string;
}) {
  return (
    <EditSheet title="Edit your watch" buttonDescription={buttonDescription}>
      {({ close, done }) => (
        <WatchForm
          cardPrintId={cardPrintId}
          versionLabel={versionLabel}
          watched={{ entryId, targetJpy }}
          onCancel={close}
          onDone={done}
        />
      )}
    </EditSheet>
  );
}
