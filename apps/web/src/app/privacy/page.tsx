import { InfoPage, InfoSection } from "@/components/info/InfoPage";
import { pageMetadata } from "@/lib/publicSeo";

// DRAFT (Collector v1 plan §G, owner decision Q8). Operator "Card Pirate",
// placeholders [CONTACT EMAIL] and [GOVERNING LAW], no personal name. Stays
// noindex with the draft banner until the owner approves the text.
export const metadata = pageMetadata(
  "Privacy policy (draft)",
  "Draft privacy policy for Card Pirate, under review.",
  "/privacy",
  undefined,
  false,
);

const CONTENTS = [
  { id: "who", label: "Who we are" },
  { id: "collect", label: "What we collect" },
  { id: "analytics", label: "Analytics and error reports" },
  { id: "providers", label: "Service providers" },
  { id: "purpose", label: "Why we use it" },
  { id: "retention", label: "How long we keep it" },
  { id: "rights", label: "Your rights" },
  { id: "transfers", label: "International transfers" },
  { id: "children", label: "Children" },
  { id: "changes", label: "Changes" },
  { id: "effective", label: "Effective date" },
] as const;

export default function PrivacyPage() {
  return (
    <InfoPage
      eyebrow="Privacy · Draft"
      title="Privacy policy"
      draft
      contents={CONTENTS}
      lede={
        <p>
          What Card Pirate collects, why, who helps us run the service, and what you can do about
          it.
        </p>
      }
    >
      <InfoSection id="who" title="Who we are">
        <p>
          Card Pirate is operated by Card Pirate. You can contact us about privacy at{" "}
          <strong>[CONTACT EMAIL]</strong>.
        </p>
      </InfoSection>

      <InfoSection id="collect" title="What we collect">
        <p>
          <strong>If you only browse</strong>, we do not ask who you are. Our hosting providers
          receive the technical details every website receives (such as your IP address, browser
          and the pages requested) in their request logs.
        </p>
        <p>
          <strong>If you sign in with Google</strong> (coming soon), we receive from Google your
          name, email address, profile picture and Google account ID. We do not receive your
          Google password and we do not store Google access tokens. A sign-in cookie keeps you
          signed in.
        </p>
        <p>
          <strong>What you add</strong>: the cards in your collection and watchlist, quantities,
          and anything you choose to enter, such as what you paid, the date and notes. Also your
          preferences, such as currency.
        </p>
      </InfoSection>

      <InfoSection id="analytics" title="Analytics and error reports">
        <p>
          <strong>Vercel Web Analytics</strong>{" "}counts page views and a few named actions (for
          example &ldquo;added a card to a collection&rdquo;). It does not use cookies. It records
          only the page type and, where relevant, a set code, never your name, email, account ID,
          quantities or what you paid.
        </p>
        <p>
          <strong>Sentry</strong> receives a report when something breaks: the error message, the
          code location, the page or API route, the browser or system type, and the app version.
          It is set up not to collect IP addresses, cookies, sign-in tokens or request bodies, and
          not to record screen sessions. Error reports do not include your account ID.
        </p>
      </InfoSection>

      <InfoSection id="providers" title="Service providers">
        <p>We use these providers to run Card Pirate. Each processes data for us under its own terms.</p>
        <ul>
          <li><strong>Vercel</strong>: website hosting and Web Analytics.</li>
          <li><strong>Railway</strong>: API servers and the database that stores accounts, collections and watchlists.</li>
          <li><strong>Cloudflare R2</strong>: storage and delivery of card images.</li>
          <li><strong>Google</strong>: sign-in (coming soon).</li>
          <li><strong>Sentry</strong>: error reports.</li>
        </ul>
      </InfoSection>

      <InfoSection id="purpose" title="Why we use it">
        <ul>
          <li>To run your account and show your collection and watchlist: needed to provide the service you asked for.</li>
          <li>To understand which pages are used and to fix errors: our legitimate interest in keeping the service working, using data that does not identify you.</li>
          <li>To keep the service secure and prevent abuse: our legitimate interest.</li>
        </ul>
        <p>We do not sell personal data and we do not use it for advertising.</p>
      </InfoSection>

      <InfoSection id="retention" title="How long we keep it">
        <ul>
          <li>Account, collection and watchlist data: until you delete your account.</li>
          <li>Request logs, analytics and error reports: for the retention period of the provider that holds them.</li>
        </ul>
      </InfoSection>

      <InfoSection id="rights" title="Your rights">
        <p>You will be able to do these yourself from your account page:</p>
        <ul>
          <li>Download a copy of your data (access and portability).</li>
          <li>Correct your collection and watchlist entries. Your name, email and picture come from Google.</li>
          <li>Delete your account, which deletes your collection, watchlist and preferences.</li>
        </ul>
        <p>
          You can also write to <strong>[CONTACT EMAIL]</strong>. Depending on where you live, you
          may have further rights, including under Malaysia&rsquo;s Personal Data Protection Act
          and the UK and EU GDPR, and you may complain to your data protection authority.
        </p>
      </InfoSection>

      <InfoSection id="transfers" title="International transfers">
        <p>
          Our providers may process data in countries other than yours, including the United
          States. Where the law requires it, we rely on the safeguards those providers offer for
          such transfers.
        </p>
      </InfoSection>

      <InfoSection id="children" title="Children">
        <p>
          Card Pirate is not directed at children under 13, or under 16 where local law sets that
          age. Please do not create an account if you are younger.
        </p>
      </InfoSection>

      <InfoSection id="changes" title="Changes">
        <p>
          We will update this page when anything changes and show the new effective date. For
          significant changes we will tell signed-in users.
        </p>
      </InfoSection>

      <InfoSection id="effective" title="Effective date">
        <p>This is a draft. It is not in effect yet.</p>
      </InfoSection>
    </InfoPage>
  );
}
