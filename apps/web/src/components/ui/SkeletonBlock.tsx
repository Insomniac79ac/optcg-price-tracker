/** Dark skeleton shimmer for loading states (design brief §9) - plain
 * Tailwind `animate-pulse` opacity pulse is enough to read as "loading",
 * deliberately not a flashy shine sweep (that reads gacha/casino). */
export function SkeletonBlock({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`animate-pulse rounded-control bg-bg-elevated ${className}`} />;
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
