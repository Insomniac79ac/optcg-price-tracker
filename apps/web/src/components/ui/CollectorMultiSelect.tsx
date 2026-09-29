"use client";

import { CollectorFilterPopover } from "./CollectorFilterPopover";
import { toggleFilter } from "@/lib/catalogueState";
import styles from "./CollectorMultiSelect.module.css";

/** Collector refinements retain checkbox multi-selection inside the shared panel. */
export function CollectorMultiSelect({ label, options, selected, onChange, optionLabel = (value) => value, optionDisabledReason, maxSelected, emptyLabel = "Any" }: {
  label: string;
  options: string[];
  selected: string[];
  onChange: (values: string[]) => void;
  optionLabel?: (value: string) => string;
  optionDisabledReason?: (value: string) => string | null;
  maxSelected?: number;
  emptyLabel?: string;
}) {
  const values = [...new Set([...options, ...selected])];
  return <CollectorFilterPopover label={label} summary={selected.length ? `${selected.length} selected` : emptyLabel}
    onClear={() => onChange([])} clearDisabled={!selected.length} searchable={values.length > 8}
    description={maxSelected !== undefined && <p className={styles.limit} role="status">{selected.length} of {maxSelected} selected.{selected.length >= maxSelected ? " Remove one to add another." : ""}</p>}>
    {(search, id) => {
      const visible = values.filter((value) => `${value} ${optionLabel(value)}`.toLowerCase().includes(search.toLowerCase()));
      return (
        <div className={styles.options} role="group" aria-label={label}>
          {visible.map((value, index) => {
            const checked = selected.includes(value);
            const reason = optionDisabledReason?.(value);
            const disabled = !checked && (Boolean(reason) || (maxSelected !== undefined && selected.length >= maxSelected));
            return <label key={value} className={styles.option} data-disabled={disabled}>
              <input type="checkbox" aria-label={optionLabel(value)} aria-describedby={reason ? `${id}-reason-${index}` : undefined} checked={checked} disabled={disabled} onChange={() => { if (!disabled) onChange(toggleFilter(selected, value)); }} />
              <span>{optionLabel(value)}{reason && <small id={`${id}-reason-${index}`} className={styles.reason}>{reason}</small>}</span>
            </label>;
          })}
          {!visible.length && <p className={styles.empty}>No matching options</p>}
        </div>
      );
    }}
  </CollectorFilterPopover>;
}
