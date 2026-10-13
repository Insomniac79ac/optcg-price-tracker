import Link from "next/link";

import { InfoPage, InfoSection } from "@/components/info/InfoPage";
import { brand } from "@/lib/brand";
import { pageMetadata } from "@/lib/publicSeo";

export const metadata = pageMetadata(
  "About",
  "Card Pirate is an independent price tracker for Japanese One Piece Card Game singles, run by Card Pirate.",
  "/about",
);

export default function AboutPage() {
  return (
    <InfoPage
      eyebrow="About"
      title="About Card Pirate"
      lede={
        <p>
          Card Pirate is an independent price tracker for Japanese One Piece Card Game singles. It
          shows what each exact version of a card is selling for, in yen, and where that price
          comes from.
        </p>
      }
    >
      <InfoSection id="what" title="What it does">
        <p>
          Every version of a card is tracked on its own. A regular art, an alternate art and a
          parallel of the same card are different cards to a collector, so they get separate
          prices and separate pages.
        </p>
        <p>
          Prices come from two Japanese sources, Yuyu-Tei and SNKRDUNK. Each card page shows the
          source prices, their dates, and the Market Index built from them. The{" "}
          <Link href="/analytics" className="text-accent-teal hover:text-accent-teal-hover">
            Market
          </Link>{" "}
          page follows the tracked value of the whole market and of each set.
        </p>
        <p>
          Collection accounts are coming: you will be able to sign in with Google and keep track
          of the cards you own and what they are worth.
        </p>
      </InfoSection>

      <InfoSection id="what-not" title="What it is not">
        <ul>
          <li>Not a shop. Card Pirate does not buy or sell cards.</li>
          <li>Not an appraisal or financial advice. Prices are estimates for information only.</li>
          <li>Not complete. Some versions have no price yet, and every total says how much of the market it covers.</li>
        </ul>
        <p>
          <Link href="/methodology" className="text-accent-teal hover:text-accent-teal-hover">
            How we price cards
          </Link>{" "}
          explains exactly which prices are used and which are left out.
        </p>
      </InfoSection>

      <InfoSection id="who" title="Who runs it">
        <p>Card Pirate is operated by Card Pirate.</p>
        <p>{brand.legalDisclaimer}</p>
        <p>{brand.imageCredit}</p>
      </InfoSection>

      <InfoSection id="contact" title="Contact">
        <p>
          Questions, corrections or a price that looks wrong: write to <strong>[CONTACT EMAIL]</strong>.
        </p>
      </InfoSection>
    </InfoPage>
  );
}
