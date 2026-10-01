import PrintClient from "./PrintClient";
import { JsonLd } from "@/components/JsonLd";
import { readPrint } from "@/lib/publicServer";
import { breadcrumbs, pageMetadata, printIdentity, printPriceTitle, printProduct } from "@/lib/publicSeo";
type Props = { params: Promise<{ id: string }> };
export async function generateMetadata({ params }: Props) {
  const { id: printId } = await params;
  const print = await readPrint(printId);
  if (!print) return pageMetadata("Card price unavailable", "This exact version could not be loaded. Search by name or code to see prices.", `/prints/${encodeURIComponent(printId)}`, undefined, false);
  const identity = printIdentity(print);
  return pageMetadata(printPriceTitle(print), `Card Pirate Market Value estimates and Japanese source prices for ${identity.name} ${print.card_code}, ${identity.detail}. See coverage and price history.`, `/prints/${print.card_print_id}`, `/share/print/${print.card_print_id}`);
}
export default async function PrintPage({ params }: Props) {
  const { id: printId } = await params;
  const print = await readPrint(printId);
  return <>{print && <><JsonLd data={printProduct(print)} /><JsonLd data={breadcrumbs([{ name: "Home", path: "/" }, { name: "Card Prices", path: "/cards" }, { name: `${printIdentity(print).name} ${print.card_code}`, path: `/prints/${print.card_print_id}` }])} /></>}<PrintClient key={printId} initialDetail={print} /></>;
}
