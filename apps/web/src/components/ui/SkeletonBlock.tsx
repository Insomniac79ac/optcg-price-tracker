/** Dark skeleton shimmer for loading states (design brief §9) - plain
 * Tailwind `animate-pulse` opacity pulse is enough to read as "loading",
 * deliberately not a flashy shine sweep (that reads gacha/casino).
 *
 * `motion-reduce:animate-none` because Tailwind does not disable animations
 * under `prefers-reduced-motion` on its own - `motion-reduce` is an opt-in
 * variant, and there is no global reduced-motion rule in globals.css. Without
 * it, a visitor who has asked for reduced motion still got a full grid of
 * twelve pulsing tiles on every /cards load, which is the largest single
 * piece of animation on the public surface. The block keeps its size and
 * surface, so it still reserves the same layout space and still reads as
 * "not loaded yet"; it simply holds still. */
export function SkeletonBlock({ className = "h-4 w-full" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-control bg-bg-elevated motion-reduce:animate-none ${className}`}
    />
  );
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonBlock key={i} className="h-4 w-full" />
      ))}
    </div>
  );
}
