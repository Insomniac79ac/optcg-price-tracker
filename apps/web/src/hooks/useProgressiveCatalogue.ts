"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchPrintCatalogue, type PrintCatalogueList, type PrintCatalogueParams } from "@/lib/prints";
import { readCatalogueSnapshot, saveCatalogueSnapshot } from "@/lib/catalogueSession";

export const CATALOGUE_BATCH_SIZE = 24;
const requests = new Map<string, Promise<PrintCatalogueList>>();
function requestBatch(params: PrintCatalogueParams) {
  const key = JSON.stringify(params);
  let request = requests.get(key);
  if (!request) {
    request = fetchPrintCatalogue(params);
    requests.set(key, request);
    const clear = () => { if (requests.get(key) === request) requests.delete(key); };
    request.then(clear, clear);
  }
  return request;
}
const dedupe = (items: PrintCatalogueList["items"]) => [...new Map(items.map((item) => [item.card_print_id, item])).values()];
interface CatalogueState {
  query: string;
  facets?: PrintCatalogueList["facets"];
  data: PrintCatalogueList | null;
  status: "loading" | "ready" | "error";
  nextOffset: number;
  appending: boolean;
  appendError: boolean;
}
const initialState = (query: string, offset: number): CatalogueState => ({ query, data: null, status: "loading", nextOffset: offset, appending: false, appendError: false });

/** Reset the data lifecycle by query without remounting filter controls: an
 * open multi-select must keep focus while desktop selections refresh results. */
export function useProgressiveCatalogue(query: string, params: PrintCatalogueParams, startOffset: number) {
  const [state, setState] = useState(() => initialState(query, startOffset));
  const [retryRequest, setRetryRequest] = useState({ query, attempt: 0 });
  const attempt = retryRequest.query === query ? retryRequest.attempt : 0;
  if (retryRequest.query !== query) setRetryRequest({ query, attempt: 0 });
  // Do not expose a prior query's rows during the render before effects run.
  const current = state.query === query ? state : initialState(query, startOffset);
  const { data, status, nextOffset, appending, appendError } = current;
  const activeSession = useRef<{ query: string; alive: boolean; busy: boolean; restoreY: number | null } | null>(null);
  const paramsKey = JSON.stringify(params);
  const requestParams = useMemo(() => JSON.parse(paramsKey) as PrintCatalogueParams, [paramsKey]);
  const sentinel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const session = { query, alive: true, busy: false, restoreY: null as number | null };
    activeSession.current = session;
    const saved = attempt === 0 ? readCatalogueSnapshot(query) : null;
    session.restoreY = saved?.scrollY ?? null;
    // Hydrate/reset a query's browser-session state after mount. Keeping this
    // in the data hook leaves the controls and their current focus intact.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState((previous) => saved ? { query, data: saved.data, facets: saved.data.facets, nextOffset: saved.nextOffset, status: "ready", appending: false, appendError: false } : { ...initialState(query, startOffset), facets: previous.facets });
    if (!saved) {
      requestBatch({ ...requestParams, limit: CATALOGUE_BATCH_SIZE, offset: startOffset }).then((result) => {
        if (!session.alive) return;
        setState({ query, facets: result.facets, data: { ...result, items: dedupe(result.items) }, nextOffset: result.items.length ? result.offset + result.items.length : result.total, status: "ready", appending: false, appendError: false });
      }, () => { if (session.alive) setState((previous) => ({ ...previous, status: "error" })); });
    }
    return () => { session.alive = false; };
  }, [query, startOffset, attempt, requestParams]);

  useEffect(() => {
    const session = activeSession.current;
    if (!data || !session || session.restoreY === null) return;
    const y = session.restoreY;
    const frame = requestAnimationFrame(() => {
      if (Math.abs(window.scrollY - y) > 2) window.scrollTo({ top: y, behavior: "instant" });
      session.restoreY = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [data]);

  const save = useCallback(() => {
    if (data) saveCatalogueSnapshot({ query, data, nextOffset, scrollY: window.scrollY });
  }, [query, data, nextOffset]);
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const link = (event.target as Element)?.closest?.('a[href]');
      if (link && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) save();
    };
    document.addEventListener("click", onClick, true);
    window.addEventListener("pagehide", save);
    return () => { document.removeEventListener("click", onClick, true); window.removeEventListener("pagehide", save); };
  }, [save]);

  const hasMore = data !== null && nextOffset < data.total;
  const loadMore = useCallback(async () => {
    const session = activeSession.current;
    if (!session?.alive || session.query !== query || session.busy || !hasMore || status !== "ready") return;
    session.busy = true;
    setState((previous) => ({ ...previous, appending: true, appendError: false }));
    try {
      const result = await requestBatch({ ...requestParams, limit: CATALOGUE_BATCH_SIZE, offset: nextOffset });
      if (!session.alive) return;
      setState((previous) => ({ ...previous, data: { ...result, items: dedupe([...(previous.data?.items ?? []), ...result.items]) }, nextOffset: result.items.length ? result.offset + result.items.length : result.total }));
    } catch {
      if (session.alive) setState((previous) => ({ ...previous, appendError: true }));
    } finally {
      session.busy = false;
      if (session.alive) setState((previous) => ({ ...previous, appending: false }));
    }
  }, [hasMore, status, nextOffset, query, requestParams]);
  useEffect(() => {
    if (!hasMore || appendError || appending || !sentinel.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadMore();
    }, { rootMargin: "400px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, appendError, appending, loadMore]);
  const retry = () => { setState((previous) => ({ ...previous, status: "loading" })); setRetryRequest({ query, attempt: attempt + 1 }); };
  return { data, facets: state.facets, status, appending, appendError, hasMore, sentinel, loadMore, save, retry };
}
