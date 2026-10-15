import type { ReactNode } from "react";

import styles from "./AccountSurface.module.css";

export { styles as accountSurfaceStyles };

/** The hero band shared by /sign-in and /account: the homepage's chart-blue
 * band, dotted sea and wave rule, with the page's own content inside. */
export function AccountHero({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <section className={styles.hero}>
      <div className={`${styles.heroContent} ${aside ? "" : styles.single}`}>
        <div>{children}</div>
        {aside}
      </div>
      <svg className={styles.wave} viewBox="0 0 1200 24" preserveAspectRatio="none" aria-hidden="true" focusable="false">
        <path d="M0 12 Q30 2 60 12 T120 12 T180 12 T240 12 T300 12 T360 12 T420 12 T480 12 T540 12 T600 12 T660 12 T720 12 T780 12 T840 12 T900 12 T960 12 T1020 12 T1080 12 T1140 12 T1200 12" />
      </svg>
    </section>
  );
}

/** A numbered chapter heading in the homepage's outlined-numeral style. */
export function AccountChapter({ id, number, title, children }: { id: string; number: string; title: string; children?: ReactNode }) {
  return (
    <div className={styles.chapter}>
      <span className={styles.chapterNumber} aria-hidden="true">{number}</span>
      <div className="min-w-0">
        <h2 id={id}>{title}</h2>
        {children && <p>{children}</p>}
      </div>
    </div>
  );
}
