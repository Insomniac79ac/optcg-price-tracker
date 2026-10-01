import PrintClient from "./PrintClient";
import { JsonLd } from "@/components/JsonLd";
import { readPrint } from "@/lib/publicServer";
import { breadcrumbs, pageMetadata, printIdentity, printProduct } from "@/lib/publicSeo";
type Props = { params: Promise<{ id: string }> };
export async function generateMetadata({ params }: Props) {
  const { id: printId } = await params;
  const print = await readPrint(printId);
  if (!print) return pageMetadata("Card price unavailable", "This exact printing could not be loaded. Find a card to compare prices.", `/prints/${encodeURIComponent(printId)}`, undefined, false);
  const identity = printIdentity(print);
  return pageMetadata(`${identity.name} ${print.card_code} Price · ${identity.detail}`, `See Japanese source prices, coverage and price history for ${identity.name} ${print.card_code}, ${identity.detail}.`, `/prints/${print.card_print_id}`, `/share/print/${print.card_print_id}`);
}
export default async function PrintPage({ params }: Props) {
  const { id: printId } = await params;
  const print = await readPrint(printId);
  return <>{print && <><JsonLd data={printProduct(print)} /><JsonLd data={breadcrumbs([{ name: "Home", path: "/" }, { name: "Card Prices", path: "/cards" }, { name: `${printIdentity(print).name} ${print.card_code}`, path: `/prints/${print.card_print_id}` }])} /></>}<PrintClient key={printId} initialDetail={print} /></>;
}
