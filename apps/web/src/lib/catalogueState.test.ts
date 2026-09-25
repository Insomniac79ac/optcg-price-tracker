import { describe, expect, it } from 'vitest';
import { collectorRefinementCount, activeFilterCount, buildCatalogueQuery, catalogueParams, EMPTY_PRINT_FILTERS, parseCatalogueState, resolveLegacyRelease, toggleFilter } from './catalogueState';
import type { ReleaseCatalogueItem } from './releases';
describe('committed catalogue URL', () => {
  it('round-trips repeated filters, release identity, search, sort and legacy offset', () => {
    const query = '?release_product_id=186&q=Zoro&rarity=SR&rarity=SEC&treatment=parallel&treatment=sp&sort=created_desc&offset=24';
    const { filters, offset } = parseCatalogueState(new URLSearchParams(query));
    expect(filters.rarities).toEqual(['SR', 'SEC']);
    expect(filters.treatments).toEqual(['parallel', 'sp']);
    expect(buildCatalogueQuery(filters, offset)).toBe(query);
    expect(catalogueParams(filters)).toMatchObject({ release_product_id: 186, rarity: ['SR','SEC'], treatment: ['parallel','sp'], q: 'Zoro', sort: 'created_desc' });
    expect(activeFilterCount(filters)).toBe(6);
  });
  it('resolves old official codes and always prefers an explicit ID', () => {
    const releases = [{release_product_id: 186, official_code: 'OP-17'}] as ReleaseCatalogueItem[];
    const legacy = parseCatalogueState(new URLSearchParams('set=OP-17')).filters;
    expect(resolveLegacyRelease(legacy, releases)).toMatchObject({releaseProductId:186, legacySet:''});
    expect(catalogueParams(parseCatalogueState(new URLSearchParams('set=OP-01&release_product_id=186')).filters)).toMatchObject({release_product_id:186,set:undefined});
    expect(catalogueParams(legacy).set).toBe('OP-17');
  });
  it('does not guess ambiguous legacy products', () => {
    const filters = {...EMPTY_PRINT_FILTERS, legacySet:'OP-17'};
    expect(resolveLegacyRelease(filters, [{official_code:'OP-17'}, {official_code:'OP-17'}] as ReleaseCatalogueItem[])).toBe(filters);
  });
  it('removes one value, resets Clear all, and validates unsafe values', () => {
    expect(toggleFilter(['SR','SEC'],'SR')).toEqual(['SEC']);
    expect(toggleFilter(['SR'],'SEC')).toEqual(['SR','SEC']);
    expect(buildCatalogueQuery(EMPTY_PRINT_FILTERS)).toBe('');
    expect(parseCatalogueState(new URLSearchParams('release_product_id=-1&offset=NaN&sort=bad')).filters).toEqual(EMPTY_PRINT_FILTERS);
  });
});

describe('collector refinement count', () => {
  it.each([
    [{ releaseProductId: 186 }, 0],
    [{ q: 'Luffy' }, 0],
    [{ rarities: ['SR'] }, 1],
    [{ rarities: ['SR', 'SEC'] }, 2],
    [{ rarities: ['SR'], treatments: ['normal', 'parallel'] }, 3],
    [{ releaseProductId: 186, q: 'Luffy', rarities: ['SR'] }, 1],
  ])('counts only rarity and treatment for %o', (filters, expected) => {
    expect(collectorRefinementCount({ ...EMPTY_PRINT_FILTERS, ...filters })).toBe(expected);
  });
});
