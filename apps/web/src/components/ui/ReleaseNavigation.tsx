"use client";
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import type { ReleaseCatalogueItem } from "@/lib/releases";
import { releaseLabel } from "@/lib/releases";
import { releaseDisplayNameEnglish } from "@/lib/releaseNames";
import styles from "@/app/cards/CardsAtlas.module.css";

export function ReleaseNavigation({ releases, status, selected, hrefFor, onSelect, onRetry }: {
  releases: ReleaseCatalogueItem[]; status: "loading" | "ready" | "error";
  selected: number | null; hrefFor: (id: number | null) => string;
  onSelect: (id: number | null) => void; onRetry: () => void;
}) {
  const trackId = useId();
  const [edges, setEdges] = useState({ previous: false, next: false });
  const scroller = useRef<HTMLElement>(null);
  const selectedRef = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    const strip = scroller.current;
    if (!strip) return;
    const measure = () => {
      const previous = strip.scrollLeft > 2;
      const next = strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 2;
      setEdges((current) => current.previous === previous && current.next === next ? current : { previous, next });
    };
    const frame = requestAnimationFrame(measure);
    strip.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(strip);
    if (strip.firstElementChild) observer?.observe(strip.firstElementChild);
    return () => {
      cancelAnimationFrame(frame);
      strip.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [releases]);
  useEffect(() => {
    // Scroll only the strip: scrollIntoView can also move the document on Back.
    const strip = scroller.current;
    const link = selectedRef.current;
    if (strip && link) strip.scrollTo?.({ left: link.offsetLeft - strip.offsetLeft - (strip.clientWidth - link.clientWidth) / 2 });
  }, [selected, releases]);
  const scroll = (direction: number) => scroller.current?.scrollBy({ left: direction * scroller.current.clientWidth * 0.8, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  const select = (event: MouseEvent<HTMLAnchorElement>, id: number | null) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); onSelect(id);
  };
  return <section className={styles.releaseSection} aria-labelledby="release-browse-title">
    <div className={styles.releaseHeadingRow}>
      <div><h2 id="release-browse-title" className={styles.sectionTitle}>Browse by release</h2><p className={styles.releaseHint}>Newest releases first · {releases.length} products</p></div>
    </div>
    <div className={styles.releaseCarousel}>
      <button type="button" className={styles.releaseArrow} aria-label="Scroll releases left" aria-controls={trackId} disabled={!edges.previous} onClick={() => scroll(-1)}>←</button>
      <div className={styles.releaseTrack} data-overflow-left={edges.previous} data-overflow-right={edges.next}>
        <nav id={trackId} ref={scroller} className={styles.releaseScroller} aria-label="Browse releases">
          <div className={styles.releaseList}>
            <a ref={!selected ? selectedRef : undefined} href={hrefFor(null)} aria-current={!selected ? 'page' : undefined} onClick={(e) => select(e, null)} className={`${styles.releaseCard} ${!selected ? styles.releaseCardSelected : ''}`}>
              <span className={styles.releaseCode}>All releases</span><span className={styles.releaseName}>Complete exact-print catalogue</span>
            </a>
            {releases.map((r) => <a key={r.release_product_id} ref={selected === r.release_product_id ? selectedRef : undefined} href={hrefFor(r.release_product_id)} onClick={(e) => select(e, r.release_product_id)} aria-label={releaseLabel(r)} aria-current={selected === r.release_product_id ? 'page' : undefined} className={`${styles.releaseCard} ${selected === r.release_product_id ? styles.releaseCardSelected : ''}`}>
              <span className={styles.releaseCode}>{r.official_code ?? 'Special product'}</span>
              {releaseDisplayNameEnglish(r.official_code) !== (r.official_code ?? "Special product") && <span className={styles.releaseName}>{releaseDisplayNameEnglish(r.official_code)}</span>}
              <span className={styles.releaseName}>{r.print_count} printings{r.released_on ? ` · ${r.released_on}` : ' · Date unavailable'}</span>
            </a>)}
          </div>
        </nav>
      </div>
      <button type="button" className={styles.releaseArrow} aria-label="Scroll releases right" aria-controls={trackId} disabled={!edges.next} onClick={() => scroll(1)}>→</button>
    </div>
    {status === 'loading' && <p className={styles.releaseLoading}>Loading releases…</p>}
    {status === 'error' && <button type="button" className={styles.retryLink} onClick={onRetry}>Retry releases</button>}
  </section>;
}
