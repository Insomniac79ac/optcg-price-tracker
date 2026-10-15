import { shortDate, yen, type HistoryPoint } from "@/lib/collection";

import styles from "./Collection.module.css";

const WIDTH = 640;
const HEIGHT = 200;
const PAD_Y = 14;

type Series = { points: HistoryPoint[]; className: string };

/** Day number since the epoch for an ISO date, so both series share one
 * calendar axis. */
function dayNumber(iso: string): number {
  return Math.round(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / 86_400_000);
}

/** SVG path for one series; a missing day (null value) breaks the line
 * instead of being drawn through, like the Market chart. */
function pathFor(points: HistoryPoint[], x: (iso: string) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  for (const point of points) {
    if (point.value_jpy === null) {
      pen = false;
      continue;
    }
    d += `${pen ? "L" : "M"}${x(point.date).toFixed(1)} ${y(point.value_jpy).toFixed(1)} `;
    pen = true;
  }
  return d.trim();
}

/** The collection's recorded value history (solid) and, when there is one,
 * the day-one preview of today's cards over the last 30 days (dashed and
 * labelled, never mistaken for the recorded line: PLAN §C4, owner Q5).
 * Draws only the API's points; nothing is interpolated. */
export function CollectionHistoryChart({
  recorded,
  preview,
  previewLabel,
}: {
  recorded: HistoryPoint[];
  preview: HistoryPoint[];
  previewLabel: string;
}) {
  const series: Series[] = [
    { points: preview, className: styles.previewLine },
    { points: recorded, className: styles.recordedLine },
  ].filter((s) => s.points.some((p) => p.value_jpy !== null));
  const all = series.flatMap((s) => s.points);
  const priced = all.filter((p): p is HistoryPoint & { value_jpy: number } => p.value_jpy !== null);
  if (priced.length < 2) {
    return <p className={styles.chartEmpty}>The history chart starts once your cards have two days of prices.</p>;
  }

  const days = all.map((p) => dayNumber(p.date));
  const first = Math.min(...days);
  const last = Math.max(...days);
  const low = Math.min(...priced.map((p) => p.value_jpy));
  const high = Math.max(...priced.map((p) => p.value_jpy));
  const span = high - low || Math.max(1, high * 0.05);
  const x = (iso: string) => (last === first ? WIDTH / 2 : ((dayNumber(iso) - first) / (last - first)) * WIDTH);
  const y = (v: number) => PAD_Y + (1 - (v - low) / span) * (HEIGHT - PAD_Y * 2);
  const firstIso = all.find((p) => dayNumber(p.date) === first)?.date ?? null;
  const lastIso = all.find((p) => dayNumber(p.date) === last)?.date ?? null;
  const hasRecorded = recorded.some((p) => p.value_jpy !== null);
  const hasPreview = preview.some((p) => p.value_jpy !== null);

  return (
    <figure className={styles.chart}>
      <div className={styles.chartFrame}>
        <span className={styles.axisHigh}>{yen(high)}</span>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Collection value from ${shortDate(firstIso)} to ${shortDate(lastIso)}, between ${yen(low)} and ${yen(high)}.`}
          className={styles.chartSvg}
        >
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={f} x1="0" x2={WIDTH} y1={HEIGHT * f} y2={HEIGHT * f} className={styles.gridLine} />
          ))}
          {series.map((s) => (
            <path key={s.className} d={pathFor(s.points, x, y)} className={s.className} />
          ))}
        </svg>
        <span className={styles.axisLow}>{yen(low)}</span>
      </div>
      <div className={styles.axisDates} aria-hidden="true">
        <span>{shortDate(firstIso)}</span>
        <span>{shortDate(lastIso)}</span>
      </div>
      <figcaption className={styles.legend}>
        {hasRecorded && (
          <span className={styles.legendItem}>
            <span className={styles.legendRecorded} aria-hidden="true" />
            Your collection, as recorded each day
          </span>
        )}
        {hasPreview && (
          <span className={styles.legendItem}>
            <span className={styles.legendPreview} aria-hidden="true" />
            {previewLabel}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
