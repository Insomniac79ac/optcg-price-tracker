import type { ReactNode } from "react";

/** The responsive column count every catalogue grid surface shares (design
 * brief Phase 5): 2 columns on small mobile, 3 from larger mobile/small
 * tablet, 4 on desktop, 5 only once there's room for it not to crowd card
 * readability. CardGridSkeleton uses the exact same classes so a loading
 * grid never reflows into a different column count once real tiles land. */
export const CARD_GRID_CLASS = "grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-5";

export function CardGrid({ children }: { children: ReactNode }) {
  return <div className={CARD_GRID_CLASS}>{children}</div>;
}
