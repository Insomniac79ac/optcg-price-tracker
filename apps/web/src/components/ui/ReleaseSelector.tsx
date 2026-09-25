import { releaseLabel, type ReleaseCatalogueItem } from "@/lib/releases";

/** Release is browse context. The parent owns committed or mobile draft state. */
export function ReleaseSelector({ releases, selected, onChange }: {
  releases: ReleaseCatalogueItem[];
  selected: number | null;
  onChange: (id: number | null) => void;
}) {
  const release = releases.find((item) => item.release_product_id === selected);
  const selectedLabel = release ? releaseLabel(release) : selected ? "Selected release" : "All releases";
  return <label className="flex min-w-0 flex-col gap-1.5 text-xs text-text-secondary">
    Release
    <select value={selected ?? ""} title={selectedLabel}
      onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)}
      className="min-h-12 w-full min-w-0 truncate rounded-control border border-border-default bg-bg-elevated px-2 text-xs text-text-primary focus-visible:outline-2 focus-visible:outline-accent-teal">
      <option value="">All releases</option>
      {selected && !release && <option value={selected}>Selected release</option>}
      {releases.map((item) => <option key={item.release_product_id} value={item.release_product_id}>{releaseLabel(item)}</option>)}
    </select>
  </label>;
}
