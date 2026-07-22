import { Badge } from "./Badge";

/** Compact pill for the currently-active saved view - the one deliberately
 * fully-rounded badge shape in the app (everything else uses the small
 * `rounded-control` corner radius; this is a pill, not a badge, on purpose -
 * see docs/interface_design_system.md "Saved views"). Renders nothing when
 * no view is active, rather than an empty pill. */
export function SavedViewPill({ name }: { name: string | null | undefined }) {
  if (!name) return null;
  return (
    <Badge
      label={name}
      className="!rounded-full bg-accent-gold/10 text-accent-gold ring-1 ring-inset ring-accent-gold/30"
    />
  );
}
