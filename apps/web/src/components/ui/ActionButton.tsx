import { forwardRef, type ButtonHTMLAttributes } from "react";

export type ActionButtonVariant = "default" | "primary" | "dry-run" | "preview" | "real" | "danger";

/** Button variants encode the admin-safety tiers from the design brief §6:
 * dry-run = blue/cyan dashed, preview = gold, a pending real write = red
 * outline ("real"), and the final destructive/confirmed action = solid red
 * ("danger"). Consolidates the button className strings that were
 * hand-typed per page (card-duplicates, source-mapping-quality, ...). */
const VARIANT_CLASS: Record<ActionButtonVariant, string> = {
  default: "border border-border-default text-text-secondary hover:text-text-primary",
  primary: "bg-accent-gold text-black/80 hover:bg-accent-gold-hover",
  "dry-run": "admin-dry-run",
  preview: "admin-preview",
  real: "admin-real-action",
  danger: "admin-danger",
};

export const ActionButton = forwardRef<
  HTMLButtonElement,
  { variant?: ActionButtonVariant } & ButtonHTMLAttributes<HTMLButtonElement>
>(function ActionButton(
  {
    variant = "default",
    className = "",
    children,
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      {...props}
      className={`rounded-control px-2.5 py-1.5 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-teal/60 disabled:cursor-not-allowed disabled:opacity-40 ${VARIANT_CLASS[variant]} ${className}`}
    >
      {children}
    </button>
  );
});
