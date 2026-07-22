import type { ReactNode } from "react";

/** Groups a set of admin action buttons (typically ActionButton variants)
 * under a consistent panel, with room for a short description above the
 * button row. Use ConfirmActionModal alongside it for anything that needs
 * a confirmation gate before firing. */
export function AdminActionPanel({
  title,
  description,
  children,
}: {
  title?: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="panel p-3">
      {title && <div className="mb-1.5 text-sm font-medium text-text-primary">{title}</div>}
      {description && <p className="mb-2 text-xs text-text-secondary">{description}</p>}
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}
