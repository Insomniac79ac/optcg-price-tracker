import { CARD_GRID_CLASS } from "./CardGrid";
import { SkeletonBlock } from "./SkeletonBlock";

/** Loading placeholder for the /cards catalogue grid - same column classes
 * as CardGrid so tiles land in the same layout once data arrives, no
 * reflow. Each placeholder tile mirrors a real tile's shape (image block,
 * two text lines, a price line) rather than a single generic bar. */
export function CardGridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div className={CARD_GRID_CLASS} aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="vault-card flex flex-col overflow-hidden rounded-panel">
          <SkeletonBlock className="aspect-[63/88] w-full rounded-none" />
          <div className="flex flex-col gap-1.5 p-2.5">
            <SkeletonBlock className="h-4 w-4/5" />
            <SkeletonBlock className="h-3 w-3/5" />
            <SkeletonBlock className="h-4 w-2/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
