"use client";

import { useEffect } from "react";

import { CompassMark } from "@/components/brand/CompassMark";
import { reportError } from "@/lib/reportError";

import styles from "./StatusPage.module.css";
import { StatusWave } from "./StatusWave";

/** Root error boundary - Next.js requires this to be a Client Component.
 * Deliberately does not render <AppHeader /> (which itself does client-side
 * data fetching via useSession) - if the error originated in shared shell
 * state, re-rendering that same shell here could throw again. Kept minimal
 * and self-contained on purpose: the homepage's look with literal colours
 * and the compass mark, nothing stateful. */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
    reportError(error);
  }, [error]);

  return (
    <div className={styles.root}>
      <main className={styles.band}>
        <div className={styles.content}>
          <p className={styles.mark} aria-hidden="true">
            <CompassMark />
            <span>CARD<span>PIRATE</span></span>
          </p>
          <h1 className={styles.title}>This page couldn’t be loaded.</h1>
          <p className={styles.body}>Try again, or head back to Home.</p>
          <div className={styles.actions}>
            <button type="button" onClick={reset} className={styles.primary}>
              Try again
            </button>
            <a href="/" className={styles.secondary}>
              Back to Home
            </a>
          </div>
        </div>
        <StatusWave />
      </main>
    </div>
  );
}
