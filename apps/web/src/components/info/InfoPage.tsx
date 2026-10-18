import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { AtlasVisualSystem } from "@/components/ui/AtlasPrimitives";

import styles from "./InfoPage.module.css";

type Contents = ReadonlyArray<{ id: string; label: string }>;

/** Shared long-form reading layout for the public info pages (About,
 * Methodology, Privacy, Terms), in the public shell. Calm and readable first:
 * one ~70ch Manrope column. Type and motifs are the homepage's own: mono
 * kicker, italic 800 title on the dotted hero band, wave rule, and chapter
 * headings with outlined numerals.
 * Desktop: the column and a sticky contents rail share the footer's
 * max-w-7xl/px-4 container, so page and footer start on the same edge.
 * Mobile: contents collapse into a disclosure, and each section links back.
 * Draft legal pages carry a visible banner (`draft`); their route metadata is
 * noindex (see each page's `metadata`). */
export function InfoPage({
  eyebrow,
  title,
  lede,
  draft = false,
  contents,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: ReactNode;
  draft?: boolean;
  contents?: Contents;
  children: ReactNode;
}) {
  const hasContents = Boolean(contents && contents.length > 0);
  return (
    <div className={`min-h-screen ${styles.root}`}>
      <AppHeader />
      <AtlasVisualSystem>
        <main className={`mx-auto max-w-7xl px-4 pb-6 pt-6 sm:pt-10 ${styles.page}`}>
          <div className="lg:grid lg:grid-cols-[minmax(0,46rem)_15rem] lg:justify-between lg:gap-12">
            <article className={styles.article}>
              <header className={styles.hero}>
                <p className={styles.kicker}>{eyebrow}</p>
                <h1 className={styles.title}>{title}</h1>
                <div className={styles.lede}>{lede}</div>
              </header>

              {draft && <DraftBanner />}

              {hasContents && (
                <details id="contents" className={`${styles.disclosure} mt-6 scroll-mt-20 lg:hidden`}>
                  <summary>
                    On this page <span>({contents!.length} sections)</span>
                  </summary>
                  <ContentsList contents={contents!} />
                </details>
              )}

              <div className={hasContents ? styles.sections : undefined}>{children}</div>
              <InfoWave />
            </article>

            {hasContents && (
              <nav aria-label="On this page" className="hidden lg:block">
                <div className={`sticky top-24 ${styles.rail}`}>
                  <p className={styles.railLabel}>On this page</p>
                  <ContentsList contents={contents!} />
                </div>
              </nav>
            )}
          </div>
        </main>
      </AtlasVisualSystem>
    </div>
  );
}

/** The homepage's repeating current marks; decorative. */
function InfoWave() {
  return <svg className={styles.wave} viewBox="0 0 1200 24" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <path d="M0 12 Q30 2 60 12 T120 12 T180 12 T240 12 T300 12 T360 12 T420 12 T480 12 T540 12 T600 12 T660 12 T720 12 T780 12 T840 12 T900 12 T960 12 T1020 12 T1080 12 T1140 12 T1200 12" />
  </svg>;
}

function ContentsList({ contents }: { contents: Contents }) {
  return (
    <ol className={styles.contents}>
      {contents.map((item) => (
        <li key={item.id}>
          <a href={`#${item.id}`}>
            {item.label}
          </a>
        </li>
      ))}
    </ol>
  );
}

export function DraftBanner() {
  return (
    <div
      role="note"
      data-draft-banner
      className="mt-6 rounded-control border border-accent-coral/50 bg-accent-coral/10 px-4 py-3 text-sm leading-6 text-text-primary"
    >
      <p className="font-semibold">Draft – under review</p>
      <p className="mt-1 text-text-secondary">
        This text is not in effect yet and will change before Card Pirate opens sign-in to the public.
        Items in [square brackets] are still to be decided.
      </p>
    </div>
  );
}

/** One titled section. `id` is its anchor in the page's `contents`; sections
 * are numbered as chapters (01, 02, ...) by CSS, in document order. */
export function InfoSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className={`${styles.section} scroll-mt-20`}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      <div className="mt-3 space-y-3 text-[15px] leading-7 text-text-secondary [&_li]:pl-1 [&_strong]:font-semibold [&_strong]:text-text-primary [&_ul]:list-disc [&_ul]:space-y-1.5 [&_ul]:pl-5">
        {children}
      </div>
      <a href="#contents" className={styles.backLink}>
        Back to contents
      </a>
    </section>
  );
}
