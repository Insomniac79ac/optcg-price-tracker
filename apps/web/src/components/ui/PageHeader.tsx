import type { ReactNode } from "react";

/** Replaces the repeated `<h1>...</h1><p>...</p>` header block duplicated
 * across every page (dashboard, card-duplicates, ...). */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-4">
      <div className="flex items-baseline justify-between gap-3">
        <h1 className="text-lg font-semibold text-text-primary">{title}</h1>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {description && <p className="mt-1 text-sm text-text-secondary">{description}</p>}
    </div>
  );
}
