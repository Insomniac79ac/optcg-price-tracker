"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { MarketValueHero } from "@/components/ui/MarketValueHero";
import { MarketValueMostValuableSection, MarketValueMoversSection } from "@/components/ui/MarketValueDiscovery";
import { MarketValueComparison } from "@/components/ui/MarketValueComparison";
import { MarketValueReleaseMarket } from "@/components/ui/MarketValueReleaseMarket";
import { ApiError } from "@/lib/api";
import { fetchMarketValue, fetchMarketValueReleases, marketScopeUrl, parseMarketRelease, type MarketValue, type MarketValueMode, type MarketValueRelease, type MarketValueWindow } from "@/lib/marketValue";

export default function MarketPage({ initialData = null }: { initialData?: MarketValue | null }) {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-[1280px] px-3 py-5 sm:px-6 sm:py-9">
        {initialData ? <MarketView initialData={initialData} /> : <Suspense fallback={<MarketLoading />}><MarketView initialData={initialData} /></Suspense>}
      </main>
    </div>
  );
}

function MarketLoading() {
  return <MarketValueHero data={null} busy error={null} releases={[]} releasesFailed={false} releaseProductId={null} window="7d" mode="performance" onScopeChange={() => {}} onWindowChange={() => {}} onModeChange={() => {}} onRetry={() => {}} />;
}

function MarketView({ initialData }: { initialData: MarketValue | null }) {
  const searchParams = useSearchParams();
  const releaseProductId = parseMarketRelease(searchParams.get("release_product_id"));
  const [window, setWindow] = useState<MarketValueWindow>("7d");
  const [mode, setMode] = useState<MarketValueMode>("performance");
  const [attempt, setAttempt] = useState(0);
  const [releases, setReleases] = useState<{ items: MarketValueRelease[]; failed: boolean; loading: boolean }>({ items: [], failed: false, loading: true });
  const [settled, setSettled] = useState<{ key: string; data: MarketValue | null; error: string | null } | null>(initialData ? { key: `${initialData.release_product_id ?? "overall"}:7d:0`, data: initialData, error: null } : null);
  const key = `${releaseProductId ?? "overall"}:${window}:${attempt}`;

  // The catalogue request is independent: its failure must not block Overall
  // or a shared release URL. Scope always uses the ID, never a card-code prefix.
  useEffect(() => {
    let cancelled = false;
    fetchMarketValueReleases().then((response) => {
      if (!cancelled) setReleases({ items: response.items, failed: false, loading: false });
    }).catch(() => {
      if (!cancelled) setReleases({ items: [], failed: true, loading: false });
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (releaseProductId === "invalid") return;
    let cancelled = false;
    fetchMarketValue(releaseProductId, window).then((data) => {
      if (!cancelled) setSettled({ key, data, error: null });
    }).catch((error: unknown) => {
      if (!cancelled) setSettled({ key, data: null, error: error instanceof ApiError && error.status === 404 ? "This release could not be found." : "This Market view could not be loaded." });
    });
    return () => { cancelled = true; };
  }, [key, releaseProductId, window]);

  const invalid = releaseProductId === "invalid";
  const busy = !invalid && settled?.key !== key;
  function changeScope(id: number | null) {
    globalThis.window.history.pushState(null, "", marketScopeUrl(id));
    globalThis.window.dispatchEvent(new PopStateEvent("popstate"));
  }
  // Keep the last settled scope, headline, dates and chart together while
  // loading. A response from an abandoned request cannot replace this view.
  return <><MarketValueHero
    data={invalid ? null : settled?.data ?? null}
    busy={busy}
    error={invalid ? "Choose a valid release to explore." : busy ? null : settled?.error ?? null}
    releases={releases.items}
    releasesFailed={releases.failed}
    releaseProductId={releaseProductId}
    window={window}
    mode={mode}
    onScopeChange={changeScope}
    onWindowChange={setWindow}
    onModeChange={setMode}
    onRetry={() => setAttempt((value) => value + 1)}
  />
    {!invalid && <>
      <MarketValueMoversSection releaseProductId={releaseProductId} />
      <MarketValueMostValuableSection releaseProductId={releaseProductId} releaseCode={releases.items.find((release) => release.release_product_id === releaseProductId)?.release_code ?? null} />
    </>}
    <MarketValueComparison releases={releases.items} loading={releases.loading} failed={releases.failed} />
    <MarketValueReleaseMarket releases={releases.items} loading={releases.loading} failed={releases.failed} onScopeChange={(id) => {
      changeScope(id);
      globalThis.window.scrollTo({ top: 0, behavior: globalThis.window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    }} />
    <section className="mt-10 max-w-3xl space-y-3 text-sm leading-7 text-text-secondary"><h2 className="text-lg font-semibold text-text-primary">Understanding Market Value</h2><p>Tracked Market Value is the value in JPY of one copy of each printing we can currently price in the selected market. It is a partial basket, not the value of every One Piece card. Adding or removing priced cards can change that total.</p><p>Price movement compares eligible cards across published periods. Missing or insufficient history is shown as unavailable, not zero. Check the coverage beside each figure before treating it as a wider market trend.</p><p>The published date describes the market series. It does not mean every source was checked then. Each card’s source observations have their own dates.</p></section>
  </>;
}
