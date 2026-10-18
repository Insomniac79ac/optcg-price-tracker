"use client";

import Link from "next/link";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { formatJpy } from "@/lib/format";
import { meRequest, ShelfRequestError, type CollectorShelf } from "@/lib/collectorShelf";
import { numberDigits } from "@/lib/groupedNumber";

import { GroupedNumberInput } from "./GroupedNumberInput";

import styles from "./PrintCollectorActions.module.css";

// The API's own limits (services/api/app/accounts/schemas.py).
export const MAX_QUANTITY = 9999;
export const MAX_JPY = 100_000_000;

type Panel = "none" | "collection" | "watch";

/** "Add to collection" and "Watch" for the exact version this page shows
 * (Collector v1 S6, PLAN E1). The version is the page's own card print, so
 * there is no picker: what you add is exactly what you are looking at.
 *
 * A visitor who is not signed in as a collector gets an invitation to sign in
 * that comes back here. Nothing renders when collector accounts are switched
 * off on the API. */
export function PrintCollectorActions({
  cardPrintId,
  versionLabel,
  shelf,
}: {
  cardPrintId: number;
  /** How this version is named on the page, e.g. "Roronoa Zoro (OP01-025) · Alternate art". */
  versionLabel: string;
  shelf: CollectorShelf;
}) {
  const [open, setOpen] = useState<Panel>("none");

  if (shelf.status === "disabled") return null;

  const headingId = `collector-actions-${cardPrintId}`;
  return (
    <section className={styles.panel} aria-labelledby={headingId} data-testid="print-collector-actions">
      <h2 id={headingId} className={styles.heading}>Your collection</h2>
      {shelf.status === "loading" && <div className={styles.placeholder} aria-hidden="true" />}
      {shelf.status === "visitor" && <SignInInvite cardPrintId={cardPrintId} />}
      {shelf.status === "error" && (
        <p className={styles.line}>
          Your collection couldn’t be loaded right now.{" "}
          <button type="button" className={styles.textButton} onClick={shelf.refresh}>Try again</button>
        </p>
      )}
      {shelf.status === "ready" && (
        <ReadyActions
          cardPrintId={cardPrintId}
          versionLabel={versionLabel}
          shelf={shelf}
          open={open}
          setOpen={setOpen}
        />
      )}
    </section>
  );
}

function SignInInvite({ cardPrintId }: { cardPrintId: number }) {
  const back = `/prints/${cardPrintId}`;
  return (
    <>
      <p className={styles.line}>Keep this exact version in your collection, or watch its price.</p>
      <div className={styles.buttons}>
        <Link href={`/sign-in?callbackUrl=${encodeURIComponent(back)}`} className={styles.secondary}>
          Sign in to add it
        </Link>
      </div>
    </>
  );
}

function ReadyActions({
  cardPrintId,
  versionLabel,
  shelf,
  open,
  setOpen,
}: {
  cardPrintId: number;
  versionLabel: string;
  shelf: CollectorShelf;
  open: Panel;
  setOpen: (panel: Panel) => void;
}) {
  const held = shelf.held.get(cardPrintId) ?? null;
  const watched = shelf.watched.get(cardPrintId) ?? null;
  const done = () => {
    setOpen("none");
    shelf.refresh();
  };

  return (
    <>
      <div className={styles.status}>
        {held ? (
          <p className={styles.owned} data-testid="in-collection">
            In your collection <span className={styles.count}>×{held.quantity}</span>
            {held.paidJpyPerCard !== null && <span className={styles.meta}>You paid {formatJpy(held.paidJpyPerCard)} each</span>}
          </p>
        ) : (
          <p className={styles.line}>Not in your collection yet.</p>
        )}
        {watched && (
          <p className={styles.watching} data-testid="watching">
            Watching
            <span className={styles.meta}>
              {watched.targetJpy !== null ? `Target ${formatJpy(watched.targetJpy)}` : "No target price"}
            </span>
          </p>
        )}
      </div>

      {open === "none" && (
        <div className={styles.buttons}>
          <button type="button" className={held ? styles.secondary : styles.primary} onClick={() => setOpen("collection")}>
            {held ? "Edit in collection" : "Add to collection"}
          </button>
          <button type="button" className={styles.secondary} onClick={() => setOpen("watch")}>
            {watched ? "Edit watch" : "Watch"}
          </button>
        </div>
      )}

      {open === "collection" && (
        <CollectionForm
          cardPrintId={cardPrintId}
          versionLabel={versionLabel}
          held={held}
          onCancel={() => setOpen("none")}
          onDone={done}
        />
      )}
      {open === "watch" && (
        <WatchForm cardPrintId={cardPrintId} versionLabel={versionLabel} watched={watched} onCancel={() => setOpen("none")} onDone={done} />
      )}
    </>
  );
}

/** Whole yen from a free-text field: blank is "not given" (null); anything
 * else must be a whole number in range or the form says so. Commas, ¥, 円 and
 * full-width digits are read the way GroupedNumberInput reads them. */
export function parseYen(raw: string, { allowZero }: { allowZero: boolean }): number | null | "invalid" {
  const cleaned = numberDigits(raw);
  if (cleaned === "") return null;
  if (cleaned === null) return "invalid";
  const value = Number(cleaned);
  if (!Number.isSafeInteger(value) || value > MAX_JPY || (!allowZero && value === 0)) return "invalid";
  return value;
}

function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function failureMessage(error: unknown): ReactNode {
  if (error instanceof ShelfRequestError && error.status === 401) {
    return "Your sign-in has ended. Sign in again to save this.";
  }
  if (error instanceof ShelfRequestError && error.status === 409) {
    return "This version is already on your list. Reload to see it.";
  }
  return "That didn’t save. Please try again in a moment.";
}

/** Add, edit or remove one collection entry. Shared by the print page's
 * panel and the /collection edit sheet; an existing entry (`held`) is edited
 * by its own id, so a "needs a version" entry with no print can still be
 * edited or removed. */
export function CollectionForm({
  cardPrintId,
  versionLabel,
  held,
  onCancel,
  onDone,
}: {
  cardPrintId: number | null;
  versionLabel: string;
  held: { entryId: number; quantity: number; paidJpyPerCard: number | null; acquiredOn: string | null } | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const id = useId();
  const [quantity, setQuantity] = useState(String(held?.quantity ?? 1));
  const [paid, setPaid] = useState(held?.paidJpyPerCard != null ? String(held.paidJpyPerCard) : "");
  const [acquiredOn, setAcquiredOn] = useState(held?.acquiredOn ?? "");
  const [problem, setProblem] = useState<ReactNode>(null);
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const digits = numberDigits(quantity);
    const count = Number(digits);
    if (!digits || count < 1 || count > MAX_QUANTITY) {
      setProblem(`Enter how many you have, from 1 to ${MAX_QUANTITY.toLocaleString("en")}.`);
      return;
    }
    const paidValue = parseYen(paid, { allowZero: true });
    if (paidValue === "invalid") {
      setProblem("Enter what you paid as a whole number of yen, or leave it blank.");
      return;
    }
    if (acquiredOn && acquiredOn > todayIso()) {
      setProblem("The date can’t be in the future.");
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      const fields = { quantity: count, paid_jpy_per_card: paidValue, acquired_on: acquiredOn || null };
      if (held) await meRequest("PATCH", `collection/${held.entryId}`, fields);
      else if (cardPrintId !== null) await meRequest("POST", "collection", { card_print_id: cardPrintId, ...fields });
      else return;
      onDone();
    } catch (error) {
      setProblem(failureMessage(error));
      setBusy(false);
    }
  }

  async function remove() {
    if (!held) return;
    setBusy(true);
    setProblem(null);
    try {
      await meRequest("DELETE", `collection/${held.entryId}`);
      onDone();
    } catch (error) {
      setProblem(failureMessage(error));
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate aria-label={held ? "Edit in your collection" : "Add to your collection"}>
      <p className={styles.formFor}>{versionLabel}</p>
      <div className={styles.fields}>
        <label htmlFor={`${id}-qty`} className={styles.label}>
          How many
          <GroupedNumberInput
            id={`${id}-qty`}
            value={quantity}
            onValueChange={setQuantity}
            className={styles.input}
            required
          />
        </label>
        <label htmlFor={`${id}-paid`} className={styles.label}>
          <span>What you paid per card <span className={styles.optional}>(¥, optional)</span></span>
          <GroupedNumberInput
            id={`${id}-paid`}
            placeholder="e.g. 1,200"
            value={paid}
            onValueChange={setPaid}
            className={styles.input}
          />
        </label>
        <label htmlFor={`${id}-date`} className={styles.label}>
          <span>When you got it <span className={styles.optional}>(optional)</span></span>
          <input
            id={`${id}-date`}
            type="date"
            max={todayIso()}
            value={acquiredOn}
            onChange={(e) => setAcquiredOn(e.target.value)}
            className={styles.input}
          />
        </label>
      </div>
      <p className={styles.hint}>Only you can see your collection.</p>
      {problem && <p role="alert" className={styles.problem}>{problem}</p>}
      <div className={styles.buttons}>
        <button type="submit" className={styles.primary} disabled={busy}>
          {busy ? "Saving…" : held ? "Save" : "Add to collection"}
        </button>
        <button type="button" className={styles.secondary} onClick={onCancel} disabled={busy}>Cancel</button>
        {held && !confirmRemove && (
          <button type="button" className={styles.textButton} onClick={() => setConfirmRemove(true)} disabled={busy}>
            Remove from collection
          </button>
        )}
      </div>
      {held && confirmRemove && (
        <div className={styles.confirm} role="group" aria-label="Confirm removal">
          <p>Remove this version from your collection?</p>
          <div className={styles.buttons}>
            <button type="button" className={styles.danger} onClick={remove} disabled={busy}>Yes, remove it</button>
            <button type="button" className={styles.secondary} onClick={() => setConfirmRemove(false)} disabled={busy}>Keep it</button>
          </div>
        </div>
      )}
    </form>
  );
}

export function WatchForm({
  cardPrintId,
  versionLabel,
  watched,
  onCancel,
  onDone,
}: {
  /** null for a watch that still needs a version: edit only, never a POST. */
  cardPrintId: number | null;
  versionLabel: string;
  watched: { entryId: number; targetJpy: number | null } | null;
  onCancel: () => void;
  onDone: () => void;
}) {
  const id = useId();
  const [target, setTarget] = useState(watched?.targetJpy != null ? String(watched.targetJpy) : "");
  const [problem, setProblem] = useState<ReactNode>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = parseYen(target, { allowZero: false });
    if (value === "invalid") {
      setProblem("Enter a target price as a whole number of yen above zero, or leave it blank.");
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      if (watched) await meRequest("PATCH", `watchlist/${watched.entryId}`, { target_jpy: value });
      else if (cardPrintId !== null) await meRequest("POST", "watchlist", { card_print_id: cardPrintId, target_jpy: value });
      onDone();
    } catch (error) {
      setProblem(failureMessage(error));
      setBusy(false);
    }
  }

  async function stop() {
    if (!watched) return;
    setBusy(true);
    setProblem(null);
    try {
      await meRequest("DELETE", `watchlist/${watched.entryId}`);
      onDone();
    } catch (error) {
      setProblem(failureMessage(error));
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate aria-label={watched ? "Edit watch" : "Watch this version"}>
      <p className={styles.formFor}>{versionLabel}</p>
      <div className={styles.fields}>
        <label htmlFor={`${id}-target`} className={styles.label}>
          <span>Target price <span className={styles.optional}>(¥, optional)</span></span>
          <GroupedNumberInput
            id={`${id}-target`}
            placeholder="e.g. 5,000"
            value={target}
            onValueChange={setTarget}
            className={styles.input}
          />
        </label>
      </div>
      <p className={styles.hint}>Your watchlist shows how far today’s value is from your target. No emails are sent.</p>
      {problem && <p role="alert" className={styles.problem}>{problem}</p>}
      <div className={styles.buttons}>
        <button type="submit" className={styles.primary} disabled={busy}>
          {busy ? "Saving…" : watched ? "Save" : "Watch"}
        </button>
        <button type="button" className={styles.secondary} onClick={onCancel} disabled={busy}>Cancel</button>
        {watched && (
          <button type="button" className={styles.textButton} onClick={stop} disabled={busy}>Stop watching</button>
        )}
      </div>
    </form>
  );
}
