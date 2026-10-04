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
  productName: "Card Pirate",
  /** Short form - use in tight UI chrome (topbar, mobile nav, favicon alt). */
  shortName: "Card Pirate",
  /** The endorsing/parent brand shown in the full lockup and footer. */
  parentBrand: "CardPirateTCG",
  /** `by {parentBrand}`, precomputed since every lockup needs this exact string. */
  endorsementLine: "by CardPirateTCG",

  tagline: "Know your cards. Know the market.",
  supportingLine: "Collect the story. Know the value.",

  /** One sentence, no jargon - the product's actual promise to a collector. */
  productDescription:
    "Track card prices, collection value and the One Piece market.",

  /** <title> default when a page doesn't set its own. */
  metadataTitleDefault: "Card Pirate — One Piece Card Prices & Collection Value",
  /** Applied by Next.js metadata to any page that sets `title: "X"` -> "X — CardPirate Atlas". */
  metadataTitleTemplate: "%s — Card Pirate",

  metadataDescription:
    "Track card prices, collection value and the One Piece market.",

  /** Shorter than metadataDescription - for OG/social cards and share sheets. */
  socialSharingDescription:
    "Track card prices, collection value and the One Piece market.",

  /** Footer/legal disclaimer - must never imply official status. */
  legalDisclaimer:
    "Card Pirate is an independent collector tool. It is not affiliated with, endorsed by, or sponsored by Bandai, Shueisha, Toei Animation, or any other rights holder connected to One Piece.",

  /** Canonical public navigation labels - functional, not novelty-themed
   * (docs/brand.md "Copy principles" - retained regardless of tone pass). */
  nav: {
    discover: "Home",
    cards: "Card Prices",
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
