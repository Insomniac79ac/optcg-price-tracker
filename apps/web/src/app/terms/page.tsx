import Link from "next/link";

import { InfoPage, InfoSection } from "@/components/info/InfoPage";
import { brand } from "@/lib/brand";
import { pageMetadata } from "@/lib/publicSeo";

// DRAFT (Collector v1 plan §G, owner decision Q8). Operator "Card Pirate",
// placeholders [CONTACT EMAIL] and [GOVERNING LAW], no personal name. Stays
// noindex with the draft banner until the owner approves the text.
export const metadata = pageMetadata(
  "Terms of use (draft)",
  "Draft terms of use for Card Pirate, under review.",
  "/terms",
  undefined,
  false,
);

const CONTENTS = [
  { id: "service", label: "The service" },
  { id: "estimates", label: "Prices are estimates" },
  { id: "accounts", label: "Accounts and acceptable use" },
  { id: "content", label: "Your content" },
  { id: "trademarks", label: "Trademarks" },
  { id: "liability", label: "Liability" },
  { id: "termination", label: "Ending your account" },
  { id: "law", label: "Governing law" },
  { id: "changes", label: "Changes and contact" },
] as const;

const link = "text-accent-teal hover:text-accent-teal-hover";

export default function TermsPage() {
  return (
    <InfoPage
      eyebrow="Terms · Draft"
      title="Terms of use"
      draft
      contents={CONTENTS}
      lede={<p>The rules for using Card Pirate. By using the site you agree to them.</p>}
    >
      <InfoSection id="service" title="The service">
        <p>
          Card Pirate is operated by Card Pirate. It is an independent price tracker for Japanese
          One Piece Card Game singles. Signed-in collectors will be able to record the cards they
          own and watch, and see what they are worth. The service is free and may change or stop.
        </p>
      </InfoSection>

      <InfoSection id="estimates" title="Prices are estimates">
        <p>
          Prices and values on Card Pirate are estimates for information only, built from public
          source prices as described in{" "}
          <Link href="/methodology" className={link}>How we price cards</Link>. They are not offers
          to buy or sell, not appraisals, and not financial advice. We do not guarantee that any
          price is accurate, complete or up to date, or that the service will always be available.
        </p>
      </InfoSection>

      <InfoSection id="accounts" title="Accounts and acceptable use">
        <p>You are responsible for activity on your account. Please do not:</p>
        <ul>
          <li>scrape, copy or bulk-download Card Pirate&rsquo;s data or pages by automated means;</li>
          <li>overload, probe or interfere with the service or its security;</li>
          <li>use the service for anything unlawful, or to harm or deceive others.</li>
        </ul>
        <p>We may suspend accounts that break these rules.</p>
      </InfoSection>

      <InfoSection id="content" title="Your content">
        <p>
          Your collection and watchlist data are yours. You give us permission to store them and to
          show them to you, only so we can provide the service. See the{" "}
          <Link href="/privacy" className={link}>privacy policy</Link> for how we handle them.
        </p>
      </InfoSection>

      <InfoSection id="trademarks" title="Trademarks">
        <p>{brand.legalDisclaimer}</p>
        <p>{brand.imageCredit}</p>
      </InfoSection>

      <InfoSection id="liability" title="Liability">
        <p>
          To the extent the law allows, Card Pirate is provided &ldquo;as is&rdquo;, and we are not
          liable for losses arising from your use of the service or reliance on its prices,
          including any buying or selling decision. Nothing in these terms limits liability that
          cannot be limited by law.
        </p>
      </InfoSection>

      <InfoSection id="termination" title="Ending your account">
        <p>
          You can delete your account at any time from your account page, which deletes your
          collection and watchlist. We may close accounts that break these terms, or close the
          service with reasonable notice where we can.
        </p>
      </InfoSection>

      <InfoSection id="law" title="Governing law">
        <p>These terms are governed by <strong>[GOVERNING LAW]</strong>.</p>
      </InfoSection>

      <InfoSection id="changes" title="Changes and contact">
        <p>
          We will update this page when the terms change and show the new effective date. Questions:{" "}
          <strong>[CONTACT EMAIL]</strong>.
        </p>
        <p>This is a draft. It is not in effect yet.</p>
      </InfoSection>
    </InfoPage>
  );
}
