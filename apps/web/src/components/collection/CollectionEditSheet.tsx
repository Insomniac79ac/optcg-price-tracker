"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { CollectionForm } from "@/components/ui/PrintCollectorActions";

import styles from "./Collection.module.css";

/** "Edit" on a /collection card: the shared collection form in a sheet that
 * rises from the bottom on a phone and sits centred on a desktop. Saving or
 * removing refreshes the page from the API, so every number shown afterwards
 * is the server's again. */
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
            <h2 id={titleId} className={styles.sheetTitle}>Edit in your collection</h2>
            <CollectionForm
              cardPrintId={cardPrintId}
              versionLabel={versionLabel}
              held={{ entryId, quantity, paidJpyPerCard, acquiredOn }}
              onCancel={() => setOpen(false)}
              onDone={() => {
                setOpen(false);
                router.refresh();
              }}
            />
          </div>
        </div>
      )}
    </>
  );
}
