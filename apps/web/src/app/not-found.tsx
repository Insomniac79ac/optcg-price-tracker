import Link from "next/link";

import { AppHeader } from "@/components/AppHeader";

import styles from "./StatusPage.module.css";
import { StatusWave } from "./StatusWave";

/** The 404 page - Next.js renders this automatically for any unmatched
 * route. Kept in the same voice as the rest of the app (plain, collector-
 * led copy, no novelty pirate terminology) rather than a generic "oops"
 * illustration. It can render under any path, so it asks for the public
 * shell explicitly. */
export default function NotFound() {
  return (
    <div className={styles.root}>
      <AppHeader publicShell />
      <main>
        <section className={styles.band}>
          <div className={styles.content}>
            <p className={styles.kicker}>Page not found · 404</p>
            <h1 className={styles.title}>This chart doesn&rsquo;t lead anywhere.</h1>
            <p className={styles.body}>The page you&rsquo;re looking for doesn&rsquo;t exist, or has moved.</p>
            <div className={styles.actions}>
              <Link href="/" className={styles.primary}>Back to Home</Link>
              <Link href="/cards" className={styles.secondary}>Browse card prices</Link>
            </div>
          </div>
          <StatusWave />
        </section>
      </main>
    </div>
  );
}
