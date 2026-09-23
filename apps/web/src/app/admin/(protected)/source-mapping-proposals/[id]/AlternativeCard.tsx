import { AdminStatusBadge } from "@/components/admin/AdminPage";
import { formatDateTime } from "@/lib/format";
import type { ProposalReviewAlternative } from "@/lib/proposalReview";
import { EvidenceList, KeyValue, ProposalArtwork, releaseDisplayName } from "../ProposalReviewComponents";
import styles from "./AlternativeCard.module.css";

export function AlternativeCard({ alternative }: { alternative: ProposalReviewAlternative }) {
  const cardName = alternative.canonical_card.name_en ?? alternative.canonical_card.name_jp ?? alternative.canonical_card.card_code;
  return <article className={`${styles.card} ${alternative.recommended ? styles.recommended : ""}`} aria-label={`${alternative.canonical_card.card_code} ${cardName} printing`}>
    <div className={styles.title}>
      <div><p className="mono text-xs text-text-muted">{alternative.canonical_card.card_code}</p><h3 className="mt-1 break-words font-semibold text-text-primary">{cardName}</h3></div>
      {alternative.recommended && <AdminStatusBadge>Recommended proposal</AdminStatusBadge>}
    </div>
    <div className={styles.body}>
      <div className={styles.artwork}><ProposalArtwork print={alternative} alt={`${cardName} ${alternative.printing_label ?? "printing"} artwork`} size="detail" /></div>
      <div className={styles.content}>
        <dl className={styles.metadata} data-print-metadata="primary">
          <KeyValue label="Exact release">{releaseDisplayName(alternative.release)}</KeyValue>
          <KeyValue label="Printing label">{alternative.printing_label ?? "Not stored"}</KeyValue>
          <KeyValue label="Special print">{alternative.special_print_label ?? "None"}</KeyValue>
          <KeyValue label="Official rarity">{alternative.official_rarity ?? "Not stored"}</KeyValue>
          <KeyValue label="Treatment">{alternative.treatment ?? "Not stored"}</KeyValue>
          <KeyValue label="Language">{["ja", "jp"].includes(alternative.language) ? "Japanese" : alternative.language}</KeyValue>
          <KeyValue label="Print state">{alternative.is_active ? "Active" : "Inactive"} · {alternative.verification_status}</KeyValue>
        </dl>
        <details className={styles.technical}>
          <summary>Technical print metadata</summary>
          <dl className={styles.metadata}>
            <KeyValue label="Alternative ID">{alternative.alternative_id}</KeyValue>
            <KeyValue label="CardPrint ID">{alternative.card_print_id}</KeyValue>
            <KeyValue label="Official asset variant">{alternative.official_asset_variant ?? "Not stored"}</KeyValue>
            <KeyValue label="Official block icon">{alternative.official_block_icon ?? "Not stored"}</KeyValue>
            <KeyValue label="Official name">{alternative.official_name ?? "Not stored"}</KeyValue>
            <KeyValue label="Artwork key" technical>{alternative.artwork_key ?? "Not stored"}</KeyValue>
            <KeyValue label="Artist">{alternative.artist ?? "Not stored"}</KeyValue>
            <KeyValue label="Review disposition">{alternative.review_disposition}</KeyValue>
            <KeyValue label="Reviewed at">{formatDateTime(alternative.reviewed_at)}</KeyValue>
            <KeyValue label="Alternative created">{formatDateTime(alternative.created_at)}</KeyValue>
            <KeyValue label="Alternative updated">{formatDateTime(alternative.updated_at)}</KeyValue>
          </dl>
        </details>
        {alternative.official_effect_text && <details className={styles.technical}><summary>Official effect text</summary><p className="mt-2 whitespace-pre-wrap break-words text-sm text-text-secondary">{alternative.official_effect_text}</p></details>}
        {([
          ["Supporting evidence", alternative.supporting_evidence],
          ["Missing evidence", alternative.missing_evidence],
          ["Conflict reasons", alternative.conflict_reasons],
        ] as const).map(([title, values]) => <section key={title} className={styles.evidence}><h4>{title}</h4><EvidenceList values={values} /></section>)}
        {alternative.review_notes && <p className="break-words text-sm text-text-secondary">Review notes: {alternative.review_notes}</p>}
      </div>
    </div>
  </article>;
}
