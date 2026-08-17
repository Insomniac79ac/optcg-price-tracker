import { CARD_GRID_CLASS } from "./CardGrid";
import { SkeletonBlock } from "./SkeletonBlock";

/** Loading placeholder for the /cards catalogue grid - same column classes
 * as CardGrid so tiles land in the same layout once data arrives, no
 * reflow. Each placeholder tile mirrors a real tile's shape and surface
 * (charcoal panel, inset artwork block, the identity rows, the Market Index
 * caption and value, and the two source columns under their rule) rather
 * than a single generic bar, so the swap to real tiles doesn't change the
 * grid's colour, spacing or height either.
 *
 * The bar heights and the gaps between them deliberately track
 * PrintCardTile's lower block line for line - it is the whole point of this
 * component. Change the tile's lower block and this has to move with it, or
 * every tile in the grid jumps the moment real data lands. */
export function CardGridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div className={CARD_GRID_CLASS} aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="flex flex-col rounded-panel border border-border-muted bg-bg-elevated p-2"
        >
          <SkeletonBlock className="aspect-[63/88] w-full" />
          <div className="flex flex-col gap-1.5 px-0.5 pt-2.5">
            {/* name */}
            <SkeletonBlock className="h-[19px] w-4/5" />
            {/* code, set */}
            <SkeletonBlock className="h-2.5 w-3/5" />
            {/* treatment, rarity */}
            <SkeletonBlock className="h-5 w-2/5" />

            <div className="pt-3">
              {/* MARKET INDEX caption over its value */}
              <SkeletonBlock className="h-2.5 w-1/2" />
              <SkeletonBlock className="mt-1.5 h-[18px] w-3/5" />

              <div className="mt-2.5 grid grid-cols-2 gap-x-2 border-t border-border-muted pt-2">
                {[0, 1].map((col) => (
                  <div key={col}>
                    <SkeletonBlock className="h-2.5 w-full" />
                    <SkeletonBlock className="mt-1.5 h-[13px] w-4/5" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
