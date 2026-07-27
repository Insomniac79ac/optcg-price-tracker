import type { ReactNode } from "react";

import { EmptyState } from "@/components/StateBlocks";

/** Catalogue-specific "nothing here" state (design brief "collector-
 * oriented empty state, never an empty analytics panel") - same boxed shell
 * as the generic EmptyState, with room for a title, a short collector-
 * voiced explanation, and an action (e.g. "Clear filters"). */
export function CollectorEmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <EmptyState>
      <div className="flex flex-col items-center gap-2">
        <p className="text-sm font-medium text-text-secondary">{title}</p>
        {children && <p className="max-w-sm text-text-faint">{children}</p>}
        {action && <div className="mt-1">{action}</div>}
      </div>
    </EmptyState>
  );
}
