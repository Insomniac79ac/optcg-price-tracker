import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { fetchPrintCatalogue } from '@/lib/prints';
import { fetchReleases } from '@/lib/releases';
import { catalogueFixture, printFixture, releaseFixture } from '@/lib/publicDiscoveryFixtures';
import Page from './page';
let search='';
vi.mock('next/navigation',()=>({useSearchParams:()=>new URLSearchParams(search),usePathname:()=>'/cards'}));
vi.mock('@/components/AppHeader',()=>({AppHeader:()=>null}));
vi.mock('@/lib/prints',async()=>({...await vi.importActual<typeof import('@/lib/prints')>('@/lib/prints'),fetchPrintCatalogue:vi.fn()}));
vi.mock('@/lib/releases',async()=>({...await vi.importActual<typeof import('@/lib/releases')>('@/lib/releases'),fetchReleases:vi.fn()}));
const matchMedia=window.matchMedia;
let intersect: IntersectionObserverCallback;
const observe=vi.fn();
beforeEach(()=>{
  search='';sessionStorage.clear();window.history.replaceState(null,'','/cards');
  vi.mocked(fetchReleases).mockReset().mockResolvedValue(releaseFixture);
  vi.mocked(fetchPrintCatalogue).mockReset().mockImplementation(async p=>catalogueFixture(Array.from({length:24},(_,i)=>printFixture((p?.offset??0)+i+1)),72,p?.offset??0));
  vi.stubGlobal('IntersectionObserver',class {constructor(cb:IntersectionObserverCallback){intersect=cb;}observe=observe;disconnect=vi.fn();});
  HTMLDialogElement.prototype.showModal=vi.fn(function(this:HTMLDialogElement){this.open=true;this.querySelector<HTMLElement>('button')?.focus();});
  HTMLDialogElement.prototype.close=vi.fn(function(this:HTMLDialogElement){this.open=false;});
  vi.spyOn(window,'scrollTo').mockImplementation(()=>{});
});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();window.matchMedia=matchMedia;});
async function ready(){const view=render(<Page/>);await screen.findByRole('link',{name:/^Print 1,/});return view;}
const tiles=()=>screen.getAllByRole('link').filter(a=>a.getAttribute('href')?.startsWith('/prints/'));
describe('release-first collector discovery',()=>{
  it('retains server order including same-day rows and six undated products',async()=>{
    await ready();
    const strip=within(screen.getByRole('navigation',{name:'Browse releases'}));
    expect(strip.getAllByRole('link').slice(1).map(a=>a.getAttribute('href'))).toEqual(releaseFixture.items.map(r=>`/cards?release_product_id=${r.release_product_id}`));
    expect(strip.getAllByRole('link')[1]).toHaveTextContent('OP-17');
    const options=within(screen.getByRole('combobox',{name:'Release'})).getAllByRole('option');
    expect(options.slice(-6).every(o=>o.textContent?.includes('Special product'))).toBe(true);
  });
  it('uses selector and strip navigation, and restores All releases',async()=>{
    const push=vi.spyOn(window.history,'pushState');const view=await ready();
    fireEvent.change(screen.getByRole('combobox',{name:'Release'}),{target:{value:'186'}});
    expect(push).toHaveBeenLastCalledWith(null,'','/cards?release_product_id=186');
    search='release_product_id=186';view.rerender(<Page/>);
    await waitFor(()=>expect(fetchPrintCatalogue).toHaveBeenLastCalledWith(expect.objectContaining({release_product_id:186,offset:0})));
    expect(screen.getByRole('link',{name:"OP-17 — The World's Strongest Warriors"})).toHaveAttribute('aria-current','page');
    fireEvent.click(screen.getByRole('link',{name:/All releases/}));
    expect(push).toHaveBeenLastCalledWith(null,'','/cards');
  });
  it('resolves legacy codes and ignores conflicting set when ID exists',async()=>{
    search='set=OP-01&release_product_id=186';await ready();
    expect(fetchPrintCatalogue).toHaveBeenLastCalledWith(expect.objectContaining({release_product_id:186}));
    expect(vi.mocked(fetchPrintCatalogue).mock.lastCall?.[0]?.set).toBeUndefined();
  });
  it('resolves a legacy set to its authoritative ReleaseProduct',async()=>{
    search='set=OP-17';await ready();
    expect(fetchPrintCatalogue).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({release_product_id:186}));
    expect(vi.mocked(fetchPrintCatalogue).mock.lastCall?.[0]?.set).toBeUndefined();
  });
  it('renders mixed-code OP17 membership and authoritative name unchanged',async()=>{
    search='release_product_id=186';vi.mocked(fetchPrintCatalogue).mockResolvedValue(catalogueFixture([printFixture(99,{card_code:'OP01-001',release_product_code:'OP-01'})]));
    render(<Page/>);const link=await screen.findByRole('link',{name:/^Print 99,/});
    expect(link).toHaveAttribute('href','/prints/99');expect(link).toHaveTextContent('OP01-001');expect(link).toHaveTextContent('Found in OP-17');
  });
  it('arrows are visible labelled controls and move the strip only',async()=>{
    await ready(); const strip=screen.getByRole('navigation',{name:'Browse releases'});strip.scrollBy=vi.fn();
    Object.defineProperty(strip,'clientWidth',{value:600});
    fireEvent.click(screen.getByRole('button',{name:'Scroll releases right'}));expect(strip.scrollBy).toHaveBeenCalledWith({left:480,behavior:'smooth'});
    fireEvent.click(screen.getByRole('button',{name:'Scroll releases left'}));expect(strip.scrollBy).toHaveBeenLastCalledWith({left:-480,behavior:'smooth'});
  });
  it('commits desktop multi-select immediately, counts selections and removes one chip',async()=>{
    search='rarity=SR&treatment=parallel&treatment=sp';const view=await ready();const push=vi.spyOn(window.history,'pushState');
    fireEvent.click(screen.getByRole('button',{name:/^Rarity/}));
    fireEvent.click(screen.getByRole('checkbox',{name:'Secret Rare'}));expect(push).toHaveBeenLastCalledWith(null,'','/cards?rarity=SR&rarity=SEC&treatment=parallel&treatment=sp');
    search='rarity=SR&rarity=SEC&treatment=parallel&treatment=sp';view.rerender(<Page/>);
    await waitFor(()=>expect(fetchPrintCatalogue).toHaveBeenLastCalledWith(expect.objectContaining({rarity:['SR','SEC'],treatment:['parallel','sp']})));
    expect(screen.getByRole('heading',{name:'Collector filters · 4'})).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Remove rarity filter Super Rare'}));expect(push).toHaveBeenLastCalledWith(null,'','/cards?rarity=SEC&treatment=parallel&treatment=sp');
    fireEvent.click(within(screen.getByLabelText('Active catalogue filters')).getByRole('button',{name:'Clear all'}));expect(push).toHaveBeenLastCalledWith(null,'','/cards');
  });
  it('keeps the dropdown and focused option mounted during immediate query refreshes', async () => {
    const view = await ready();
    const trigger = screen.getByRole('button', { name: 'Rarity Any' });
    fireEvent.click(trigger);
    const option = screen.getByRole('checkbox', { name: 'Super Rare' });
    option.focus();
    let resolve!: (data: ReturnType<typeof catalogueFixture>) => void;
    vi.mocked(fetchPrintCatalogue).mockReturnValueOnce(new Promise(r => { resolve = r; }));
    fireEvent.click(option);
    search = 'rarity=SR'; view.rerender(<Page />);
    expect(screen.getByRole('button', { name: 'Rarity 1 selected' })).toBe(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('checkbox', { name: 'Super Rare' })).toBe(option);
    expect(option).toHaveFocus(); expect(option).toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Secret Rare' }));
    expect(window.location.search).toBe('?rarity=SR&rarity=SEC');
    await act(async () => resolve(catalogueFixture([printFixture(1)])));
  });
  it('returns to the beginning of changed results after deep scrolling',async()=>{
    await ready();const results=document.getElementById('catalogue-results')!;
    vi.spyOn(results,'getBoundingClientRect').mockReturnValue({top:-2000} as DOMRect);
    results.scrollIntoView=vi.fn();
    fireEvent.click(screen.getByRole('button',{name:/^Rarity/}));
    fireEvent.click(screen.getByRole('checkbox',{name:'Secret Rare'}));
    expect(results.scrollIntoView).toHaveBeenCalledExactlyOnceWith({block:'start',behavior:'instant'});
  });
  it('mobile edits a multi-select draft and commits only once on Apply',async()=>{
    window.matchMedia=vi.fn().mockImplementation(query=>({matches:query.includes('max-width'),addEventListener:vi.fn(),removeEventListener:vi.fn()}));
    await ready();const push=vi.spyOn(window.history,'pushState');
    fireEvent.click(screen.getByRole('button',{name:'Filters'}));const dialog=screen.getByRole('dialog',{name:'Filters'});
    fireEvent.click(within(dialog).getByRole('button',{name:/^Rarity/}));
    for(const name of ['Super Rare','Secret Rare'])fireEvent.click(within(dialog).getByRole('checkbox',{name}));
    fireEvent.click(within(dialog).getByRole('button',{name:'Done'}));
    fireEvent.click(within(dialog).getByRole('button',{name:/^Treatment/}));
    for(const name of ['parallel','sp'])fireEvent.click(within(dialog).getByRole('checkbox',{name}));
    fireEvent.click(within(dialog).getByRole('button',{name:'Done'}));
    expect(push).not.toHaveBeenCalled();fireEvent.click(within(dialog).getByRole('button',{name:'Apply filters'}));
    expect(push).toHaveBeenCalledExactlyOnceWith(null,'','/cards?rarity=SR&rarity=SEC&treatment=parallel&treatment=sp');expect(screen.queryByRole('dialog')).toBeNull();
  });
  it('intersection appends with no history entry; manual fallback remains and end is explicit',async()=>{
    await ready();const push=vi.spyOn(window.history,'pushState');expect(tiles()).toHaveLength(24);
    act(()=>intersect([{isIntersecting:true}] as IntersectionObserverEntry[],{} as IntersectionObserver));
    await waitFor(()=>expect(tiles()).toHaveLength(48));expect(push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Load more'}));await waitFor(()=>expect(tiles()).toHaveLength(72));
    expect(screen.getByText('All 72 printings in this view loaded.')).toBeInTheDocument();expect(screen.queryByRole('button',{name:'Load more'})).toBeNull();
    expect(screen.queryByRole('navigation',{name:'Catalogue pagination'})).toBeNull();expect(fetchPrintCatalogue).toHaveBeenCalledTimes(3);
  });
  it.each(['q=Zoro','release_product_id=186','sort=created_desc','rarity=SEC'])('resets loaded rows for %s',async(query)=>{
    const view=await ready();fireEvent.click(screen.getByRole('button',{name:'Load more'}));await waitFor(()=>expect(tiles()).toHaveLength(48));
    search=query;view.rerender(<Page/>);await waitFor(()=>expect(tiles()).toHaveLength(24));expect(fetchPrintCatalogue).toHaveBeenLastCalledWith(expect.objectContaining({offset:0,limit:24}));
  });
});
