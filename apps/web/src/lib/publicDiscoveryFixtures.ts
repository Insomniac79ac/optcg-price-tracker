/** Mock public API fixtures for the focused discovery tests. */
import type { PrintCatalogueItem, PrintCatalogueList, PrintMarketIndexSourceValue } from './prints';
import type { ReleaseCatalogueItem, ReleaseCatalogueList } from './releases';
export function source(source: string, value_jpy: number | null): PrintMarketIndexSourceValue {
  return {source, value_jpy, reference_type: source === 'yuyutei' ? 'retail_sell' : 'listing_floor', evidence_type:'listing', observed_at:null, sample_size:null, stale:false, eligible:value_jpy !== null, fallback_used:false, ineligible_reason: null};
}
export function printFixture(id: number, overrides: Partial<PrintCatalogueItem> = {}): PrintCatalogueItem {
  return {
    card_print_id:id,canonical_card_id:id,card_code:`OP17-${String(id).padStart(3,'0')}`,name_en:`Print ${id}`,name_jp:null,rarity:'SR',card_type:'Character',treatment:'normal',language:'jp',release_product_id:186,release_code:'OP-17',release_name:'A new adventure',release_product_code:'OP-17',created_at:'2026-09-25T00:00:00Z',market_index_change_7d_pct:null,image_url:`https://www.onepiece-cardgame.com/images/${id}.png`,display_image:null,verification_status:'verified',source_coverage:[],latest_observation_at:null,
    market_index:{card_print_id:id,index_version:3,index_value_jpy:null,calculation_method:'median_of_sources',source_count:0,coverage_status:'none',confidence:'low',source_values:[],auxiliary_values:[],freshest_observation_at:null,stalest_eligible_source_at:null,stale_sources:[],calculated_at:'2026-09-25T00:00:00Z'}, ...overrides,
  };
}
export function catalogueFixture(items: PrintCatalogueItem[], total=items.length, offset=0): PrintCatalogueList {
  return {items,total,offset,limit:24,pagination:{total,offset,limit:24,has_next:offset+items.length<total,has_previous:offset>0,next_offset:offset+items.length<total?offset+items.length:null,previous_offset:offset>0?Math.max(0,offset-24):null},facets:{rarities:['R','SR','SEC','SP CARD'],treatments:['normal','parallel','sp'],languages:['jp'],verification_statuses:['verified']}};
}
const release = (id:number, code:string|null, date:string|null): ReleaseCatalogueItem => ({release_product_id:id,official_code:code,display_name:code ? `${code} official name` : `Special product ${id}`,released_on:date,chronology_available:date!==null,release_date_source:date?'DATE_VERIFIED_CORROBORATED':null,source_catalogue:'bandai_jp',verification_status:'verified',print_count:36,created_at:'2026-09-01T00:00:00Z'});
export const releaseFixture: ReleaseCatalogueList = {
  items:[release(186,'OP-17','2026-08-22'),release(211,'ST-31','2026-07-11'),release(212,'ST-32','2026-07-11'),release(185,'OP-16','2026-05-30'),...Array.from({length:6},(_,i)=>release(225+i,null,null))],chronology_available:true,ordering_basis:'released_on_desc_then_deterministic_fallback',
};
