import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarketCardsSection } from "./MarketCardsSection";
import { fetchMarketCards, type MarketBasis } from "@/lib/marketAnalytics";
import { catalogueFixture, printFixture, source } from "@/lib/publicDiscoveryFixtures";
import type { PrintCatalogueList } from "@/lib/prints";
vi.mock("@/lib/marketAnalytics", async () => ({
  ...await vi.importActual<typeof import("@/lib/marketAnalytics")>("@/lib/marketAnalytics"), fetchMarketCards:vi.fn(),
}));
const index: MarketBasis = {key:"market_index",kind:"market_index",source:null,reference_type:null,evidence_type:null,available:true,unavailable_reason:null,usable_priced_prints:6};
const yuyu: MarketBasis = {...index,key:"source:yuyutei",kind:"source",source:"yuyutei",reference_type:"retail_sell"};
const snkr: MarketBasis = {...yuyu,key:"source:snkrdunk",source:"snkrdunk",reference_type:"listing_floor"};
function item(id=3686) {
  const print=printFixture(id,{canonical_card_id:5,card_code:"EB04-007",name_en:"Mixed-code print",release_product_id:186,release_code:"OP-17",release_product_code:"EB-04",release_name:"世界最強の戦士達"});
  print.market_index.index_value_jpy=12500;
  print.market_index.source_values=[source("yuyutei",13000),source("snkrdunk",12000)];
  return print;
}
const props={selection:{priceBasis:"market_index"},basis:index,ready:true};
const request=vi.mocked(fetchMarketCards);
beforeEach(()=>{request.mockReset().mockResolvedValue(catalogueFixture([item()]));});
const cards=()=>screen.getAllByTestId("market-card");
async function ready(){await screen.findByTestId("market-cards-grid");}

describe("bounded Market card presentation",()=>{
  it.each([[index,"Market Index","￥12,500"],[yuyu,"Yuyu-Tei · Retail price","￥13,000"],[snkr,"SNKRDUNK · Current listing","￥12,000"]] as const)("uses selected basis $key",async(basis,label,value)=>{
    render(<MarketCardsSection {...props} basis={basis} selection={{priceBasis:basis.key}} />);
    await ready();
    expect(cards()[0]).toHaveTextContent(label);
    expect(cards()[0]).toHaveTextContent(value);
    if(basis!==index) expect(cards()[0]).not.toHaveTextContent("￥12,500");
  });

  it("renders future source/instrument vocabulary without hardcoded platform labels",async()=>{
    const future={...yuyu,key:"source:cardrush",source:"cardrush",reference_type:"auction_high"};
    const print=item();print.market_index.source_values.push(source("cardrush",9876));
    request.mockResolvedValue(catalogueFixture([print]));
    render(<MarketCardsSection {...props} basis={future} selection={{priceBasis:future.key}} />);
    await ready();expect(cards()[0]).toHaveTextContent("cardrush · Auction high");expect(cards()[0]).toHaveTextContent("￥9,876");
  });

  it.each([null,0])("does not substitute Index for an ineligible source reading %s",async(value)=>{
    const print=item();print.market_index.source_values=[{...source("snkrdunk",value),eligible:false}];
    request.mockResolvedValue(catalogueFixture([print]));
    render(<MarketCardsSection {...props} basis={snkr} selection={{priceBasis:snkr.key}} />);
    await ready();expect(cards()[0]).toHaveTextContent("Unavailable");expect(cards()[0]).not.toHaveTextContent("￥12,500");
  });

  it("preserves mixed-code physical membership, server order, and exact print links",async()=>{
    const prints=[item(3686),item(42),item(900),item(71),item(5),item(37)];
    prints[0].card_code="EB04-007";
    request.mockResolvedValue(catalogueFixture(prints));
    render(<MarketCardsSection {...props} selection={{priceBasis:index.key,release_product_id:186,rarity:"SEC"}} />);
    await ready();
    expect(request).toHaveBeenCalledExactlyOnceWith({priceBasis:index.key,release_product_id:186,rarity:"SEC"});
    expect(cards().map(c=>within(c).getByRole("link").getAttribute("href"))).toEqual(prints.map(p=>`/prints/${p.card_print_id}`));
    expect(cards()[0]).toHaveTextContent("EB04-007");expect(cards()[0]).toHaveTextContent("Found in OP-17");
    expect(cards()[0]).not.toHaveTextContent("Found in EB-04");expect(cards()[0]).not.toHaveTextContent("世界最強");
    for(const card of cards()) {
      const img=within(card).getByRole("img");
      expect(img).toHaveAttribute("loading","lazy");expect(img.className).toContain("object-contain");
    }
    expect(screen.getByRole("link",{name:"Browse these cards →"})).toHaveAttribute("href","/cards?release_product_id=186&rarity=SEC");
  });

  it("uses existing verified display-image selection instead of choosing another artwork",async()=>{
    const print=item();print.display_image={url:"https://cdn.snkrdunk.com/exact.png",source:"snkrdunk",exact_print_verified:true,geometry:null};
    request.mockResolvedValue(catalogueFixture([print]));
    render(<MarketCardsSection {...props}/>);await ready();
    expect(within(cards()[0]).getByRole("img")).toHaveAttribute("src","https://cdn.snkrdunk.com/exact.png");
  });

  it.each([
    [{priceBasis:"source:snkrdunk"},"/cards"],
    [{priceBasis:"source:snkrdunk",rarity:"SEC"},"/cards?rarity=SEC"],
    [{priceBasis:"source:snkrdunk",release_product_id:186},"/cards?release_product_id=186"],
  ])("carries only supported catalogue scope %j",async(selection,href)=>{
    render(<MarketCardsSection {...props} selection={selection} basis={snkr}/>);await ready();
    expect(screen.getByRole("link",{name:"Browse these cards →"})).toHaveAttribute("href",href);
  });
});

describe("section-local cards request state",()=>{
  it("waits for vocabulary, then makes one request without reacting to unrelated rerenders",async()=>{
    const view=render(<MarketCardsSection {...props} ready={false}/>);
    expect(request).not.toHaveBeenCalled();
    view.rerender(<MarketCardsSection {...props}/>);await ready();
    view.rerender(<MarketCardsSection {...props} selection={{priceBasis:"market_index"}}/>);
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("shows a bounded six-card skeleton only while loading",()=>{
    request.mockReturnValue(new Promise(()=>{}));render(<MarketCardsSection {...props}/>);
    expect(screen.getByRole("status",{name:"Loading cards in this market"}).children).toHaveLength(6);
  });
  it("shows an honest empty state without substituting another basis",async()=>{
    request.mockResolvedValue(catalogueFixture([]));render(<MarketCardsSection {...props} basis={snkr} selection={{priceBasis:snkr.key}}/>);
    await screen.findByText("No cards currently have a usable price for this view.");
    expect(screen.queryByRole("status")).toBeNull();expect(screen.queryAllByTestId("market-card")).toHaveLength(0);expect(request).toHaveBeenCalledTimes(1);
  });
  it("recovers from an API failure through a local Retry",async()=>{
    request.mockRejectedValueOnce(new Error("offline"));render(<MarketCardsSection {...props}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Retry cards"}));await ready();expect(request).toHaveBeenCalledTimes(2);
  });
  it("keeps settled cards, their basis price, and their destination while refreshing",async()=>{
    const view=render(<MarketCardsSection {...props}/>);await ready();
    let resolve: (data:PrintCatalogueList)=>void=()=>{};
    request.mockReturnValue(new Promise(r=>{resolve=r;}));
    view.rerender(<MarketCardsSection {...props} basis={yuyu} selection={{priceBasis:yuyu.key,release_product_id:186,rarity:"SEC"}}/>);
    expect(screen.getByTestId("market-cards-grid").closest('[aria-busy]')).toHaveAttribute("aria-busy","true");
    expect(cards()[0]).toHaveTextContent("Market Index￥12,500");
    expect(screen.getByRole("link",{name:"Browse these cards →"})).toHaveAttribute("href","/cards");
    await act(async()=>resolve(catalogueFixture([item(777)])));
    expect(cards()[0]).toHaveTextContent("Yuyu-Tei · Retail price￥13,000");
    expect(screen.getByRole("link",{name:"Browse these cards →"})).toHaveAttribute("href","/cards?release_product_id=186&rarity=SEC");
  });
  it("ignores an older scope's late response",async()=>{
    const view=render(<MarketCardsSection {...props}/>);await ready();
    let older: (data:PrintCatalogueList)=>void=()=>{};
    request.mockReturnValueOnce(new Promise(r=>{older=r;}));
    view.rerender(<MarketCardsSection {...props} selection={{priceBasis:index.key,release_product_id:185}}/>);
    request.mockResolvedValue(catalogueFixture([item(777)]));
    view.rerender(<MarketCardsSection {...props} selection={{priceBasis:index.key,release_product_id:186}}/>);
    await waitFor(()=>expect(within(cards()[0]).getByRole("link")).toHaveAttribute("href","/prints/777"));
    await act(async()=>older(catalogueFixture([item(99)])));
    expect(within(cards()[0]).getByRole("link")).toHaveAttribute("href","/prints/777");
  });
});
