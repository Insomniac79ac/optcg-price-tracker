import HomeClient from "./HomeClient";
import { pageMetadata } from "@/lib/publicSeo";
import { brand } from "@/lib/brand";
export const metadata = pageMetadata("One Piece Card Prices & Collection Value", brand.metadataDescription, "/");
metadata.title = { absolute: brand.metadataTitleDefault };
metadata.openGraph = { ...metadata.openGraph, title: brand.metadataTitleDefault };
metadata.twitter = { ...metadata.twitter, title: brand.metadataTitleDefault };
export default function HomePage() { return <HomeClient />; }
