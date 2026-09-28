"use client";

import { releaseLabel, type ReleaseCatalogueItem } from "@/lib/releases";
import { CollectorFilterPopover } from "./CollectorFilterPopover";
import styles from "./CollectorMultiSelect.module.css";

/** Release is browse context. The parent owns committed or mobile draft state. */
export function ReleaseSelector({ releases, selected, onChange }: {
  releases: ReleaseCatalogueItem[];
  selected: number | null;
  onChange: (id: number | null) => void;
}) {
  const release = releases.find((item) => item.release_product_id === selected);
  const summary = release ? release.official_code || releaseLabel(release) : selected !== null ? "Selected release" : "All releases";
  return <CollectorFilterPopover label="Release" summary={summary} searchable searchPlaceholder="Search releases…"
    clearDisabled={selected === null} onClear={() => onChange(null)}>
    {(search, id) => {
      const visible = releases.filter((item) => releaseLabel(item).toLowerCase().includes(search.trim().toLowerCase()));
      const option = (value: number | null, label: string) => <label key={value ?? "all"} className={styles.option}>
        <input type="radio" name={`${id}-release`} value={value ?? ""} checked={selected === value} onChange={() => onChange(value)} />
        <span>{label}</span>
      </label>;
      return <div className={styles.options} role="radiogroup" aria-label="Release">
        {option(null, "All releases")}
        {selected !== null && !release && option(selected, "Selected release")}
        {visible.map((item) => option(item.release_product_id, releaseLabel(item)))}
        {!visible.length && <p className={styles.empty}>No matching releases</p>}
      </div>;
    }}
  </CollectorFilterPopover>;
}
