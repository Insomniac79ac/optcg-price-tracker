import { describe, it, expect, vi, beforeEach } from 'vitest';
import { catalogueFixture, printFixture } from './publicDiscoveryFixtures';
import { toPrintUiModel, fetchPrintCatalogue } from './prints';
import { fetchHeroCatalogue, fetchRecentFinds, homeHeroPrints, isHomeHeroCategory, rotateRecentFinds } from './homeDiscovery';
vi.mock('./prints', async () => ({...await vi.importActual<typeof import('./prints')>('./prints'),fetchPrintCatalogue:vi.fn()}));
beforeEach(() => vi.mocked(fetchPrintCatalogue).mockReset());
describe('Home discovery contracts', () => {
  it('fetches recently ADDED entries with a bounded cohort', async () => {
    vi.mocked(fetchPrintCatalogue).mockResolvedValue(catalogueFixture([]));
    await fetchRecentFinds();
    expect(fetchPrintCatalogue).toHaveBeenCalledExactlyOnceWith({sort:'created_desc',limit:16});
  });
  it('queries OR eligibility as independent families using only published facets', async () => {
    vi.mocked(fetchPrintCatalogue).mockResolvedValue(catalogueFixture([printFixture(1)]));
    const prints=await fetchHeroCatalogue();
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(3);
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({rarity:['SR'],sort:'created_desc',limit:16});
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({rarity:['SP CARD'],sort:'created_desc',limit:16});
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({treatment:['parallel','sp'],sort:'created_desc',limit:16});
    expect(prints).toHaveLength(1);
  });
  it('does not invent treatment aliases when no such facet is published', async () => {
    const response=catalogueFixture([]); response.facets={...response.facets,treatments:['normal'],rarities:['SR']};
    vi.mocked(fetchPrintCatalogue).mockResolvedValue(response);
    await fetchHeroCatalogue(); expect(fetchPrintCatalogue).toHaveBeenCalledTimes(1);
  });
  it('never uses suffixes or codes as eligibility', () => {
    expect(isHomeHeroCategory(toPrintUiModel(printFixture(1,{rarity:'R',treatment:null,official_asset_variant:'p9'})))).toBe(false);
    for (const overrides of [{rarity:'SR'}, {rarity:'SPカード'}, {rarity:'SP P'}, {rarity:'R',treatment:'parallel'}, {rarity:'R',treatment:'sp'}]) expect(isHomeHeroCategory(toPrintUiModel(printFixture(2,overrides)))).toBe(true);
  });
  it('rotates three unique eligible exact printings and excludes missing or non-exact art', () => {
    const pool=Array.from({length:16},(_,i)=>toPrintUiModel(printFixture(i+1)));
    pool.push(pool[0], toPrintUiModel(printFixture(100,{image_url:null})), toPrintUiModel(printFixture(101,{display_image:{url:'https://example.test/x.png',source:'yuyutei',exact_print_verified:false,geometry:null}})));
    const selected=homeHeroPrints(pool,'2026-09-25');
    expect(selected).toHaveLength(3); expect(new Set(selected.map(p=>p.cardPrintId)).size).toBe(3);
    expect(selected).toEqual(homeHeroPrints(pool,'2026-09-25'));
    expect(selected).not.toEqual(homeHeroPrints(pool,'2026-09-26'));
    expect(selected.every(p=>p.cardPrintId<100)).toBe(true);
  });
  it('uses canonical Bandai images when owned exact artwork is unavailable', () => {
    const p=toPrintUiModel(printFixture(1,{display_image:{url:'https://www.onepiece-cardgame.com/images/1.png',source:'bandai',exact_print_verified:false,owned_asset_selected:false,geometry:null}}));
    expect(homeHeroPrints([p],'2026-09-25')).toEqual([p]);
  });
  it('excludes a Bandai display image known to differ from the canonical print', () => {
    const p=toPrintUiModel(printFixture(1,{display_image:{url:'https://www.onepiece-cardgame.com/images/other.png',source:'bandai',exact_print_verified:false,owned_asset_selected:false,geometry:null}}));
    expect(homeHeroPrints([p],'2026-09-25')).toEqual([]);
  });
  it('rotates four recent prints without priced preference', () => {
    const pool=Array.from({length:16},(_,i)=>toPrintUiModel(printFixture(i+1)));
    const a=rotateRecentFinds(pool,'2026-09-25'); expect(a).toHaveLength(4);
    expect(a.every(p=>p.marketIndexJpy===null)).toBe(true);
    expect(a).toEqual(rotateRecentFinds(pool,'2026-09-25'));
    expect(a).not.toEqual(rotateRecentFinds(pool,'2026-09-26'));
  });
});
