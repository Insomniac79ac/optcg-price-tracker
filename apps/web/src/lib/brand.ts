/**
 * Centralized brand configuration for CardPirate Atlas.
 *
 * Single source of truth for product naming, tagline and legal copy so the
 * working brand (adopted pending formal domain/trademark clearance - see
 * docs/brand.md) can change later by editing this file only, instead of
 * hunting through components. Server-safe: no secrets, no runtime
 * infrastructure URLs - importable from server or client code alike.
 *
 * Deliberately does NOT include color tokens or fonts (those live in
 * globals.css/layout.tsx as CSS, not JS) or one-off body copy that only
 * ever appears in a single place (see docs/brand.md "Copy principles" -
 * not every string needs to route through here, just the ones that
 * identify the product itself).
 */

export const brand = {
  /** Full product name - use for first mention, metadata, legal copy. */
  productName: "CardPirate Atlas",
  /** Short form - use in tight UI chrome (topbar, mobile nav, favicon alt). */
  shortName: "Atlas",
  /** The endorsing/parent brand shown in the full lockup and footer. */
  parentBrand: "CardPirateTCG",
  /** `by {parentBrand}`, precomputed since every lockup needs this exact string. */
  endorsementLine: "by CardPirateTCG",

  tagline: "Map your collection. Find your next treasure.",
  supportingLine: "Collect the story. Know the value.",

  /** One sentence, no jargon - the product's actual promise to a collector. */
  productDescription:
    "A place to remember what you own, discover what to chase, and understand value without turning collecting into trading.",

  /** <title> default when a page doesn't set its own. */
  metadataTitleDefault: "CardPirate Atlas — One Piece Card Collection & Market Index",
  /** Applied by Next.js metadata to any page that sets `title: "X"` -> "X — CardPirate Atlas". */
  metadataTitleTemplate: "%s — CardPirate Atlas",

  metadataDescription:
    "Explore One Piece cards, map your collection, follow the cards you're chasing, and view a transparent Market Index based on Japanese market sources.",

  /** Shorter than metadataDescription - for OG/social cards and share sheets. */
  socialSharingDescription:
    "Map your collection, chase what you're missing, and read the market without the noise.",

  /** Footer/legal disclaimer - must never imply official status. */
  legalDisclaimer:
    "CardPirate Atlas is an independent collector tool. It is not affiliated with, endorsed by, or sponsored by Bandai, Shueisha, Toei Animation, or any other rights holder connected to One Piece.",

  /** Canonical public navigation labels - functional, not novelty-themed
   * (docs/brand.md "Copy principles" - retained regardless of tone pass). */
  nav: {
    discover: "Discover",
    cards: "Cards",
    marketIndex: "Market Index",
    myCollection: "My Collection",
    vaultView: "Vault View",
    wishlist: "Wishlist",
    grading: "Grading",
    activity: "Activity",
    admin: "Admin",
  },
} as const;

export type Brand = typeof brand;
