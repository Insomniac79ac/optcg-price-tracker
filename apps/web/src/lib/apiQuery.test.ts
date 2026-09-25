import { describe, expect, it, vi, afterEach } from "vitest";
import { apiGet, API_URL, buildQueryString } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe('query serialization', () => {
  it('retains scalar ordering, escaping, false, zero and empty strings', () => {
    expect(buildQueryString({ q: 'Sanji & サンジ', limit: 24, offset: 0, active: false, empty: '' })).toBe('?q=Sanji+%26+%E3%82%B5%E3%83%B3%E3%82%B8&limit=24&offset=0&active=false&empty=');
  });
  it('appends repeated values in supplied order without comma joining', () => {
    expect(buildQueryString({ rarity: ['SR', 'SEC'], treatment: ['parallel', 'sp'], release_product_id: 186 })).toBe('?rarity=SR&rarity=SEC&treatment=parallel&treatment=sp&release_product_id=186');
  });
  it('omits empty arrays and nullish values, including an empty query', () => {
    expect(buildQueryString({ rarity: [], x: null, y: undefined })).toBe('');
    expect(buildQueryString()).toBe('');
    expect(buildQueryString({ numbers: [2, 1], bool: [true, false] })).toBe('?numbers=2&numbers=1&bool=true&bool=false');
  });
  it('uses the same serializer in actual apiGet requests', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetch);
    await apiGet('/prints', { params: { rarity: ['SR', 'SEC'], limit: 24, release_product_id: 186 } });
    expect(fetch).toHaveBeenCalledWith(`${API_URL}/prints?rarity=SR&rarity=SEC&limit=24&release_product_id=186`, expect.any(Object));
  });
});
