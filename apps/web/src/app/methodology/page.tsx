import { InfoPage, InfoSection } from "@/components/info/InfoPage";
import { pageMetadata } from "@/lib/publicSeo";

// Every statement on this page restates docs/market_value.md,
// docs/market_index.md, docs/agent/INVARIANTS.md or docs/collector_accounts.md.
// It explains the existing method and must not add to it: change those
// documents (and the code) first, then this page.

export const metadata = pageMetadata(
  "How we price cards",
  "How Card Pirate prices each exact One Piece card version: sources, the Market Index, Market Value, coverage and why some changes show as unavailable.",
  "/methodology",
);

const CONTENTS = [
  { id: "versions", label: "Every version is priced on its own" },
  { id: "sources", label: "Where prices come from" },
  { id: "sale-prices", label: "Sale prices are never used" },
  { id: "market-index", label: "The Market Index for each card" },
  { id: "freshness", label: "How fresh prices are" },
  { id: "market-value", label: "Market Value for the market and each set" },
  { id: "movement", label: "Price changes over 7 and 30 days" },
  { id: "unavailable", label: "Unavailable is not zero" },
  { id: "gaps", label: "Gaps in the history" },
  { id: "collection", label: "Collection value" },
  { id: "not-included", label: "What is not included" },
] as const;

export default function MethodologyPage() {
  return (
    <InfoPage
      eyebrow="Methodology"
      title="How we price cards"
      lede={
        <p>
          Card Pirate only shows prices it can trace to a real, recent observation from a named
          source. When it cannot, it says so instead of guessing. This page explains the rules.
        </p>
      }
      contents={CONTENTS}
    >
      <InfoSection id="versions" title="Every version is priced on its own">
        <p>
          The priced unit is one exact physical Japanese printing. Regular art, alternate art and
          parallel versions of the same card are separate cards with separate prices.
        </p>
        <p>
          Which set a version belongs to comes from its official release record. It is never
          guessed from the card number.
        </p>
      </InfoSection>

      <InfoSection id="sources" title="Where prices come from">
        <p>Two Japanese sources are used: Yuyu-Tei and SNKRDUNK. All prices are in yen.</p>
        <ul>
          <li>
            <strong>Yuyu-Tei retail price.</strong> The latest regular selling price, if it was
            seen in the last 7 days. Whether the shop has the card in stock does not matter.
          </li>
          <li>
            <strong>Yuyu-Tei buy price.</strong> What the shop pays for a card. It is shown for
            context only and is never part of the Market Index.
          </li>
          <li>
            <strong>SNKRDUNK.</strong> When a version has at least 3 sales in the last 30 days, the
            median of those sales. Otherwise its lowest current listing, if seen in the last 7
            days.
          </li>
        </ul>
        <p>
          Each source contributes at most one value per card, so no marketplace counts twice.
          Listings at a platform&rsquo;s minimum price, below-minimum anomalies and stale
          observations are left out.
        </p>
      </InfoSection>

      <InfoSection id="sale-prices" title="Sale prices are never used">
        <p>
          When Yuyu-Tei puts a card on sale, the sale price is not shown as the card&rsquo;s
          price, is not added to its price history, and is not used in the Market Index or Market
          Value. The crossed-out former price is never used in its place either, and neither is an
          older regular price. The card simply has no Yuyu-Tei retail price until a regular price
          returns.
        </p>
      </InfoSection>

      <InfoSection id="market-index" title="The Market Index for each card">
        <p>The Market Index combines the usable source values for one version:</p>
        <ul>
          <li>Two or more usable sources: the median of their values (full coverage).</li>
          <li>One usable source: that source&rsquo;s value (limited coverage).</li>
          <li>No usable source: no Market Index. The card shows no price, not ¥0.</li>
        </ul>
        <p>
          Card pages label each value by what it is: a retail price, a current listing or a recent
          sales median.
        </p>
      </InfoSection>

      <InfoSection id="freshness" title="How fresh prices are">
        <p>
          The target is to check every regular price successfully at least once every 24 hours.
          It is a target, not a promise, and each price shows the date it was actually observed.
        </p>
        <p>
          A failed check never makes an old price look new. When a source confirms a card has no
          listing, the old price keeps its original date.
        </p>
      </InfoSection>

      <InfoSection id="market-value" title="Market Value for the market and each set">
        <p>
          <strong>Tracked value</strong> is the sum, in yen, of one copy of each version we can
          currently price, for the whole market or for one set. It is a partial basket: versions
          without a price are left out, not counted as worthless, and the coverage (how many
          versions are priced) is always shown beside it. It is not a market capitalisation. If
          nothing is priced, there is no value rather than ¥0.
        </p>
        <p>
          A day&rsquo;s Market Value is published only after that day&rsquo;s price snapshot is
          confirmed complete.
        </p>
      </InfoSection>

      <InfoSection id="movement" title="Price changes over 7 and 30 days">
        <p>
          A change compares one day with the day before, using only the versions priced on both
          days, in the same set, from the same sources. The change for the day is the total of
          those versions today divided by their total the day before. Expensive cards therefore
          move the result more than cheap ones.
        </p>
        <ul>
          <li>
            A card that gains or loses its price does not count as a rise or a fall. It only joins
            the comparison on its next full pair of days.
          </li>
          <li>
            A day counts only if the compared versions make up at least 80% of the priced value on
            both days.
          </li>
          <li>
            The whole market also needs at least 300 compared versions and 10% of versions priced.
            A set of 30 or more versions needs at least 30 compared versions and 40% priced; a set
            of 10 to 29 needs at least 80% of its versions compared and priced (and at least 10). A
            set with fewer than 10 versions has no movement figure.
          </li>
          <li>
            7-day and 30-day changes chain every daily step in the window. Every day must be
            present and every step must pass.
          </li>
        </ul>
        <p>
          Biggest movers are ranked from the latest published daily step, by yen and by percentage.
          Their individual changes always add up to the change of the whole basket.
        </p>
        <p>
          The Card Pirate Index is a separate measure with its own rules. Neither one changes the
          other.
        </p>
      </InfoSection>

      <InfoSection id="unavailable" title="Unavailable is not zero">
        <p>
          When a change cannot be measured fairly, it is shown as unavailable, with a reason. It
          is never shown as 0%. Prices are never filled in from a nearby day, carried forward or
          estimated.
        </p>
      </InfoSection>

      <InfoSection id="gaps" title="Gaps in the history">
        <p>
          There are no price snapshots for 27 and 28 September 2026. Those days stay empty on
          purpose: nothing is invented to fill them, and no 7-day or 30-day change is measured
          across them. Published history is not rewritten afterwards.
        </p>
      </InfoSection>

      <InfoSection id="collection" title="Collection value">
        <p>When collection accounts open, your collection is valued with the same rules:</p>
        <ul>
          <li>
            Each card is worth its Market Index on the latest completed day, times the number you
            own.
          </li>
          <li>
            Cards without a price count towards coverage (&ldquo;priced 41 of 48 cards&rdquo;) and
            never add ¥0. If nothing is priced, there is no total.
          </li>
          <li>
            Changes use the same comparison and the same 80% rule, without the minimum card counts
            above, so a small collection can still have a change. Adding or removing cards is never
            shown as a gain or a loss.
          </li>
          <li>If a day in the window is missing, the change is unavailable, not 0%.</li>
        </ul>
      </InfoSection>

      <InfoSection id="not-included" title="What is not included">
        <ul>
          <li>Graded cards (such as PSA 10) are a separate category and are not in these prices.</li>
          <li>Yuyu-Tei sale prices and crossed-out former prices.</li>
          <li>Estimated, carried-forward or nearest-day prices.</li>
          <li>Sources other than Yuyu-Tei and SNKRDUNK.</li>
        </ul>
      </InfoSection>
    </InfoPage>
  );
}
