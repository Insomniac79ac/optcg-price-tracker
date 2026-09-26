import { fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchPrintCatalogue, fetchPrint } from '@/lib/prints';
import { fetchReleases } from '@/lib/releases';
import { fetchIndexMovers, type IndexMover } from '@/lib/cardPirateIndex';
import { catalogueFixture, printFixture, releaseFixture } from '@/lib/publicDiscoveryFixtures';
import Page, { buildCardsSearchHref } from './page';
const push=vi.fn();
vi.mock('next/navigation',()=>({useRouter:()=>({push})}));
vi.mock('@/components/AppHeader',()=>({AppHeader:()=>null}));
vi.mock('@/lib/prints',async()=>({...await vi.importActual<typeof import('@/lib/prints')>('@/lib/prints'),fetchPrintCatalogue:vi.fn(),fetchPrint:vi.fn()}));
vi.mock('@/lib/releases',async()=>({...await vi.importActual<typeof import('@/lib/releases')>('@/lib/releases'),fetchReleases:vi.fn()}));
vi.mock('@/lib/cardPirateIndex',async()=>({...await vi.importActual<typeof import('@/lib/cardPirateIndex')>('@/lib/cardPirateIndex'),fetchIndexMovers:vi.fn()}));
const mover=(id:number,direction:'up'|'down'='up'):IndexMover=>({card_print_id:id,card_code:'OP01-001',name:`Mover ${id}`,rarity:'SR',display_image_url:`https://www.onepiece-cardgame.com/images/${id}.png`,treatment:'parallel',language:'jp',prior_value_jpy:100,current_value_jpy:200,direction,raw_pct:direction==='up'?30.77:-12.5,capped_log_return:'0.2231',was_capped:true,contribution_log_return:'0.0001',approx_index_points:'0.1000',move_rank:id,impact_rank:id});
const moves=(count=4)=>({order:'move' as const,as_of:'2026-09-25',prior_point_date:'2026-09-24',constituent_count:100,movers_count:count,unchanged_count:100-count,chain_link_log_return:'0.001',truncated:false,movers:Array.from({length:count},(_,i)=>mover(100+i,i%2?'down':'up'))});
beforeEach(async()=>{
  await Promise.resolve();
  push.mockReset();
  vi.mocked(fetchPrintCatalogue).mockReset().mockImplementation(async p=>catalogueFixture(Array.from({length:16},(_,i)=>printFixture((p?.rarity||p?.treatment?200:1)+i))));
  vi.mocked(fetchPrint).mockReset().mockImplementation(async id=>({...printFixture(Number(id)),colors:null,artwork_key:null,siblings:[]}));
  vi.mocked(fetchReleases).mockReset().mockResolvedValue(releaseFixture);
  vi.mocked(fetchIndexMovers).mockReset().mockResolvedValue(moves());
});
const section=(name:string)=>within(screen.getByRole('region',{name}));
async function ready(){render(<Page/>);await screen.findByText('Mover 100');await waitFor(()=>expect(section('Recent finds').getAllByRole('link')).toHaveLength(4));await waitFor(()=>expect(section('Find your next card.').getAllByRole('link')).toHaveLength(3));}
describe('Home discovery',()=>{
  it('has three eligible unique hero print links separate from four unpriced recently added prints',async()=>{
    await ready();const hero=section('Find your next card.').getAllByRole('link');
    expect(new Set(hero.map(a=>a.getAttribute('href'))).size).toBe(3);expect(hero.every(a=>a.getAttribute('href')?.startsWith('/prints/2'))).toBe(true);
    expect(section('Recent finds').getAllByText('No market price yet')).toHaveLength(4);
    expect(section('Recent finds').getByText(/Recently added to Atlas/)).toBeInTheDocument();
    expect(fetchPrintCatalogue).toHaveBeenCalledWith({sort:'created_desc',limit:16});
    expect(vi.mocked(fetchPrintCatalogue).mock.calls.some(([p])=>p?.sort==='updated')).toBe(false);
  });
  it('uses releases in server chronology and authoritative release ID links',async()=>{
    const source = { ...releaseFixture, items: releaseFixture.items.map(r => ({ ...r, display_name: '世界最強の戦士' })) };
    vi.mocked(fetchReleases).mockResolvedValue(source);
    await ready();const links=section('Explore the Atlas').getAllByRole('link').filter(a=>a.getAttribute('href')?.includes('release_product_id'));
    expect(links).toHaveLength(8);expect(links.map(a=>a.getAttribute('href'))).toEqual(releaseFixture.items.slice(0,8).map(r=>`/cards?release_product_id=${r.release_product_id}`));
    expect(links[0]).toHaveTextContent("The World's Strongest Warriors");expect(links[0]).toHaveTextContent('2026-08-22');expect(fetchReleases).toHaveBeenCalledTimes(1);
    expect(section('Explore the Atlas').queryByText(/世界最強の戦士/)).toBeNull();
    expect(source.items[0].display_name).toBe('世界最強の戦士');
  });
  it('makes direction textual and signed, with current index and exact release enrichment',async()=>{
    await ready();const s=section('Cards on the move');expect(s.getAllByText('Up')).toHaveLength(2);expect(s.getAllByText('Down')).toHaveLength(2);
    expect(s.getAllByText('+30.77%')).toHaveLength(2);expect(s.getAllByText('−12.50%')).toHaveLength(2);
    expect(s.getAllByText('Market Index ￥200')).toHaveLength(4);expect(await s.findAllByText('Found in OP-17')).toHaveLength(4);
    const links=s.getAllByRole('listitem').map(li=>within(li).getByRole('link'));expect(links.map(a=>a.getAttribute('href'))).toEqual(['/prints/100','/prints/101','/prints/102','/prints/103']);
    expect(links.every(a=>a.querySelector('img')?.classList.contains('object-contain'))).toBe(true);
  });
  it('enriches at most four displayed movers in parallel and fails softly per item',async()=>{
    vi.mocked(fetchIndexMovers).mockResolvedValue(moves(8));vi.mocked(fetchPrint).mockRejectedValueOnce(new Error('offline'));
    await ready();expect(fetchPrint).toHaveBeenCalledTimes(4);expect(section('Cards on the move').getAllByRole('listitem')).toHaveLength(4);
    expect(section('Cards on the move').getByText('Mover 100')).toBeInTheDocument();expect(section('Cards on the move').getAllByText(/Found in/)).toHaveLength(3);
  });
  it('styles a zero mover neutrally without an up/down claim',async()=>{
    const data=moves(1);data.movers[0].raw_pct=0;vi.mocked(fetchIndexMovers).mockResolvedValue(data);await ready();
    expect(section('Cards on the move').getByText('Unchanged').parentElement).toHaveAttribute('data-direction','neutral');
    expect(section('Cards on the move').queryByText('Up')).toBeNull();
  });
  it('does not issue new discovery requests for typing or focus',async()=>{
    await ready();const count=vi.mocked(fetchPrintCatalogue).mock.calls.length;
    fireEvent.change(screen.getByRole('searchbox'),{target:{value:'Zoro'}});fireEvent.focus(section('Cards on the move').getByText('Mover 100'));
    expect(fetchPrintCatalogue).toHaveBeenCalledTimes(count);expect(count).toBe(4);expect(fetchIndexMovers).toHaveBeenCalledTimes(1);expect(fetchPrint).toHaveBeenCalledTimes(4);
  });
  it('shows bounded skeletons for each independent section',()=>{
    vi.mocked(fetchPrintCatalogue).mockReturnValue(new Promise(()=>{}));vi.mocked(fetchIndexMovers).mockReturnValue(new Promise(()=>{}));vi.mocked(fetchReleases).mockReturnValue(new Promise(()=>{}));render(<Page/>);
    expect(screen.getByRole('status',{name:'Loading featured printings'})).toBeInTheDocument();expect(screen.getByRole('status',{name:'Loading cards on the move'})).toBeInTheDocument();expect(screen.getByLabelText('Loading releases')).toBeInTheDocument();
  });
  it('retains every other section when Recent Finds fails, and retries independently',async()=>{
    vi.mocked(fetchPrintCatalogue).mockImplementation(async p=>{if(!p?.rarity&&!p?.treatment)throw new Error('offline');return catalogueFixture([printFixture(200),printFixture(201),printFixture(202)]);});
    render(<Page/>);const retry=await screen.findByRole('button',{name:'Retry Recent Finds'});await screen.findByText('Mover 100');expect(await screen.findByText("The World's Strongest Warriors")).toBeInTheDocument();
    vi.mocked(fetchPrintCatalogue).mockResolvedValue(catalogueFixture([printFixture(1)]));fireEvent.click(retry);expect(await screen.findByText('Print 1')).toBeInTheDocument();expect(fetchIndexMovers).toHaveBeenCalledTimes(1);
  });
  it.each(['hero','releases','movers'])('isolates %s failure',async(which)=>{
    if(which==='hero')vi.mocked(fetchPrintCatalogue).mockImplementation(async p=>{if(p?.rarity)throw new Error('offline');return catalogueFixture([printFixture(1)]);});
    if(which==='releases')vi.mocked(fetchReleases).mockRejectedValue(new Error('offline'));
    if(which==='movers')vi.mocked(fetchIndexMovers).mockRejectedValue(new Error('offline'));
    render(<Page/>);await waitFor(()=>expect(section('Recent finds').getAllByRole('link').length).toBeGreaterThan(0));
    expect(await screen.findByRole('button',{name:which==='hero'?'Retry featured printings':which==='releases'?'Retry releases':'Retry movers'})).toBeInTheDocument();
  });
  it('handles insufficient hero inventory and empty recent/movers without fabricated cards',async()=>{
    vi.mocked(fetchPrintCatalogue).mockResolvedValue(catalogueFixture([]));vi.mocked(fetchIndexMovers).mockResolvedValue(moves(0));render(<Page/>);
    expect(await screen.findByText(/More SR, SP and Parallel artwork/)).toBeInTheDocument();expect(await screen.findByText('No recently added printings are available right now.')).toBeInTheDocument();expect(await screen.findByText('No cards moved on this published day.')).toBeInTheDocument();
  });
});
describe('Home search',()=>{
  it.each(['Kaido','OP01-001','カイドウ','  Kaido  ','','   '])('submits %s without a search lookup',async term=>{
    await ready();fireEvent.change(screen.getByRole('searchbox'),{target:{value:term}});fireEvent.submit(screen.getByRole('search'));expect(push).toHaveBeenCalledWith(buildCardsSearchHref(term));expect(fetchIndexMovers).toHaveBeenCalledTimes(1);
  });
  it('bounds the search length',()=>expect(buildCardsSearchHref('a'.repeat(200))).toBe(`/cards?q=${'a'.repeat(128)}`));
});
