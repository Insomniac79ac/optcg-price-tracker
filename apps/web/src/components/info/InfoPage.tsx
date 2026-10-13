import type { ReactNode } from "react";

import { AppHeader } from "@/components/AppHeader";
import { AtlasDivider, AtlasMapSurface, AtlasVisualSystem } from "@/components/ui/AtlasPrimitives";

import styles from "./InfoPage.module.css";

type Contents = ReadonlyArray<{ id: string; label: string }>;

/** Shared long-form reading layout for the public info pages (About,
 * Methodology, Privacy, Terms). Calm and readable first: one ~70ch Manrope
 * column. The Atlas motif is the homepage's own (chart-grid header surface,
 * route-line divider, gold waypoint numbers on sections), used sparingly.
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
    <div className="min-h-screen">
      <AppHeader />
      <AtlasVisualSystem>
        <main className="mx-auto max-w-7xl px-4 pb-6 pt-6 sm:pt-10">
          <div className="lg:grid lg:grid-cols-[minmax(0,46rem)_15rem] lg:justify-between lg:gap-12">
            <article className={styles.article}>
              <AtlasMapSurface>
                <header className="px-5 py-7 sm:px-8 sm:py-9">
                  <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent-gold">{eyebrow}</p>
                  <h1 className="mt-2 font-display text-[30px] font-semibold leading-[1.1] tracking-tight text-text-primary sm:text-[38px]">
                    {title}
                  </h1>
                  <div className="mt-3 max-w-[38rem] text-[15px] leading-7 text-text-secondary">{lede}</div>
                </header>
              </AtlasMapSurface>

              {draft && <DraftBanner />}

              {hasContents && (
                <details id="contents" className="mt-6 scroll-mt-20 rounded-control border border-border-muted px-4 py-3 lg:hidden">
                  <summary className="cursor-pointer text-sm font-medium text-text-primary">
                    On this page <span className="text-text-muted">({contents!.length} sections)</span>
                  </summary>
                  <ContentsList contents={contents!} />
                </details>
              )}

              <div className={hasContents ? styles.sections : undefined}>{children}</div>
              <AtlasDivider />
            </article>

            {hasContents && (
              <nav aria-label="On this page" className="hidden lg:block">
                <div className="sticky top-24 border-l border-border-default pl-5">
                  <p className="text-xs font-medium uppercase tracking-[0.12em] text-text-muted">On this page</p>
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

function ContentsList({ contents }: { contents: Contents }) {
  return (
    <ol className={`${styles.contents} mt-3 space-y-2 text-sm`}>
      {contents.map((item) => (
        <li key={item.id}>
          <a href={`#${item.id}`} className="text-text-secondary hover:text-text-primary">
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
 * are numbered as waypoints (01, 02, ...) by CSS, in document order. */
export function InfoSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className={`${styles.section} scroll-mt-20 pt-9`}>
      <h2 className="font-display text-[22px] font-semibold leading-snug text-text-primary">{title}</h2>
      <div className="mt-3 space-y-3 text-[15px] leading-7 text-text-secondary [&_li]:pl-1 [&_strong]:font-semibold [&_strong]:text-text-primary [&_ul]:list-disc [&_ul]:space-y-1.5 [&_ul]:pl-5">
        {children}
      </div>
      <a href="#contents" className={`${styles.backLink} mt-3 text-xs text-text-muted hover:text-text-primary`}>
        Back to contents
      </a>
    </section>
  );
}
