import PrintClient from "./PrintClient";
import { JsonLd } from "@/components/JsonLd";
import { auth } from "@/lib/auth";
import { printSignInHref, signedOutPrintSignInHref } from "@/lib/printReturnPath";
import { readPrint } from "@/lib/publicServer";
import { breadcrumbs, pageMetadata, printIdentity, printPriceTitle, printProduct } from "@/lib/publicSeo";

// The signed-out invite depends on the session, so this route is rendered
// per request. The print payload stays the public read (readPrint). The
// sign-in callback is the route id only, never the query string or headers.
export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

/** Sign-in href for a visitor, or null for a collector. An id that is not
 * this page's own number is rejected before the session is read. The URL
 * itself comes only from that id. */
async function publicSignInHref(routeId: string): Promise<string | null> {
  if (!printSignInHref(routeId)) return null;
  let session: { sessionKind?: string | null } | null = null;
  try {
    session = await auth();
  } catch {
    // An unreadable session is the public page: show the invite.
  }
  return signedOutPrintSignInHref(routeId, session);
}
export async function generateMetadata({ params }: Props) {
  const { id: printId } = await params;
  const print = await readPrint(printId);
  if (!print) return pageMetadata("Card price unavailable", "This exact version could not be loaded. Search by name or code to see prices.", `/prints/${encodeURIComponent(printId)}`, undefined, false);
  const identity = printIdentity(print);
  return pageMetadata(printPriceTitle(print), `Card Pirate Market Value estimates and Japanese source prices for ${identity.name} ${print.card_code}, ${identity.detail}. See coverage and price history.`, `/prints/${print.card_print_id}`, `/share/print/${print.card_print_id}`);
}
export default async function PrintPage({ params }: Props) {
  const { id: printId } = await params;
  const [print, signedOutSignInHref] = await Promise.all([readPrint(printId), publicSignInHref(printId)]);
  return <>{print && <><JsonLd data={printProduct(print)} /><JsonLd data={breadcrumbs([{ name: "Home", path: "/" }, { name: "Card Prices", path: "/cards" }, { name: `${printIdentity(print).name} ${print.card_code}`, path: `/prints/${print.card_print_id}` }])} /></>}<PrintClient key={printId} initialDetail={print} signedOutSignInHref={signedOutSignInHref} /></>;
}
