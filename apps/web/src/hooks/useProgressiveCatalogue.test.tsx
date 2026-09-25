import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { StrictMode, type ReactNode } from 'react';
import { fetchPrintCatalogue } from '@/lib/prints';
import { catalogueFixture, printFixture } from '@/lib/publicDiscoveryFixtures';
import { useProgressiveCatalogue } from './useProgressiveCatalogue';
vi.mock('@/lib/prints', async () => ({...await vi.importActual<typeof import('@/lib/prints')>('@/lib/prints'),fetchPrintCatalogue:vi.fn()}));
const batch=(offset:number,total=72)=>catalogueFixture(Array.from({length:Math.min(24,total-offset)},(_,i)=>printFixture(offset+i+1)),total,offset);
beforeEach(() => {
  vi.mocked(fetchPrintCatalogue).mockReset().mockImplementation(async p=>batch(p?.offset??0));
  sessionStorage.clear(); window.history.replaceState(null,'','/cards');
  vi.spyOn(window,'scrollTo').mockImplementation(()=>{});
});
afterEach(()=>vi.restoreAllMocks());
describe('progressive catalogue', () => {
  it('starts with 24 and coalesces Strict Mode duplicate mounts', async () => {
    const {result}=renderHook(()=>useProgressiveCatalogue('',{sort:'index_desc'},0),{wrapper:({children}:{children:ReactNode})=><StrictMode>{children}</StrictMode>});
    await waitFor(()=>expect(result.current.data?.items).toHaveLength(24));
    expect(fetchPrintCatalogue).toHaveBeenCalledExactlyOnceWith({sort:'index_desc',limit:24,offset:0});
  });
  it('appends only 24 in order, dedupes overlapping IDs, and creates no history entries', async () => {
    const push=vi.spyOn(window.history,'pushState');
    const {result}=renderHook(()=>useProgressiveCatalogue('',{},0));
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    const overlapping=batch(24); overlapping.items[0]=printFixture(24);
    vi.mocked(fetchPrintCatalogue).mockResolvedValueOnce(overlapping);
    await act(()=>result.current.loadMore());
    expect(result.current.data?.items).toHaveLength(47);
    expect(result.current.data?.items.map(p=>p.card_print_id)).toEqual([...Array.from({length:24},(_,i)=>i+1),...Array.from({length:23},(_,i)=>i+26)]);
    expect(push).not.toHaveBeenCalled();
    expect(fetchPrintCatalogue).toHaveBeenLastCalledWith({limit:24,offset:24});
  });
  it('rejects parallel append attempts synchronously', async () => {
    const {result}=renderHook(()=>useProgressiveCatalogue('',{},0));
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    let resolve!: (data:ReturnType<typeof batch>)=>void;
    vi.mocked(fetchPrintCatalogue).mockReturnValueOnce(new Promise(r=>{resolve=r;}));
    act(()=>{ void result.current.loadMore(); void result.current.loadMore(); });
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(2);
    await act(async()=>resolve(batch(24)));
    expect(result.current.data?.items).toHaveLength(48);
  });
  it('retains cards on append error, retries, then stops at the server total', async () => {
    vi.mocked(fetchPrintCatalogue).mockResolvedValueOnce(batch(0,48)).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(batch(24,48));
    const {result}=renderHook(()=>useProgressiveCatalogue('',{},0));
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    await act(()=>result.current.loadMore());
    expect(result.current.appendError).toBe(true); expect(result.current.data?.items).toHaveLength(24);
    await act(()=>result.current.loadMore());
    expect(result.current.appendError).toBe(false); expect(result.current.data?.items).toHaveLength(48); expect(result.current.hasMore).toBe(false);
    await act(()=>result.current.loadMore()); expect(fetchPrintCatalogue).toHaveBeenCalledTimes(3);
  });
  it('honors an incoming offset as the start, then progresses from it', async () => {
    const {result}=renderHook(()=>useProgressiveCatalogue('?offset=24',{},24));
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    expect(result.current.data?.items[0].card_print_id).toBe(25);
    await act(()=>result.current.loadMore());
    expect(fetchPrintCatalogue).toHaveBeenLastCalledWith({limit:24,offset:48});
    expect(result.current.data?.items).toHaveLength(48);
  });
  it('restores loaded depth and scroll from the same history entry without fetching again', async () => {
    const query='?q=Zoro&rarity=SR&rarity=SEC';
    const first=renderHook(()=>useProgressiveCatalogue(query,{q:'Zoro',rarity:['SR','SEC']},0));
    await waitFor(()=>expect(first.result.current.status).toBe('ready'));
    await act(()=>first.result.current.loadMore());
    vi.spyOn(window,'scrollY','get').mockReturnValue(1240);
    act(()=>first.result.current.save());
    const savedState=window.history.state;
    first.unmount(); window.history.replaceState(savedState,'',`/cards${query}`);
    vi.spyOn(window,'scrollY','get').mockReturnValue(0);
    const second=renderHook(()=>useProgressiveCatalogue(query,{q:'Zoro',rarity:['SR','SEC']},0));
    await waitFor(()=>expect(second.result.current.data?.items).toHaveLength(48));
    await waitFor(()=>expect(window.scrollTo).toHaveBeenCalledWith({top:1240,behavior:'instant'}));
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(2);
    expect(window.history.scrollRestoration).not.toBe('manual');
  });
  it('still browses when session storage is unavailable', async () => {
    vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('blocked');});
    const {result}=renderHook(()=>useProgressiveCatalogue('',{},0));
    await waitFor(()=>expect(result.current.status).toBe('ready'));
    expect(()=>result.current.save()).not.toThrow();
    await act(()=>result.current.loadMore()); expect(result.current.data?.items).toHaveLength(48);
  });
});
