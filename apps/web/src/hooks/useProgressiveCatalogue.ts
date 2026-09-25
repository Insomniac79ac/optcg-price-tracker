"use client";
import { useCallback, useEffect, useRef, useState } from "react";
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

/** Mount with key=query so a committed filter change owns a fresh lifecycle. */
export function useProgressiveCatalogue(query: string, params: PrintCatalogueParams, startOffset: number) {
  const [data, setData] = useState<PrintCatalogueList | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [appending, setAppending] = useState(false);
  const [appendError, setAppendError] = useState(false);
  const [nextOffset, setNextOffset] = useState(startOffset);
  const [attempt, setAttempt] = useState(0);
  const alive = useRef(false);
  const busy = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const restoreY = useRef<number | null>(null);
  const paramsRef = useRef(params);
  useEffect(() => {
    alive.current = true;
    let active = true;
    const saved = attempt === 0 ? readCatalogueSnapshot(query) : null;
    if (saved) {
      restoreY.current = saved.scrollY;
      // Restore before the next paint after rows mount; never replace native
      // restoration with a global manual mode.
      // Restoring browser-session state must happen after hydration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setData(saved.data);
      setNextOffset(saved.nextOffset);
      setStatus("ready");
    } else {
      requestBatch({ ...paramsRef.current, limit: CATALOGUE_BATCH_SIZE, offset: startOffset }).then((result) => {
        if (!active) return;
        setData({ ...result, items: dedupe(result.items) });
        setNextOffset(result.items.length ? result.offset + result.items.length : result.total);
        setStatus("ready");
      }, () => { if (active) setStatus("error"); });
    }
    return () => { active = false; alive.current = false; };
  }, [query, startOffset, attempt]);

  useEffect(() => {
    if (!data || restoreY.current === null) return;
    const y = restoreY.current;
    const frame = requestAnimationFrame(() => {
      if (Math.abs(window.scrollY - y) > 2) window.scrollTo({ top: y, behavior: "instant" });
      restoreY.current = null;
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
    if (busy.current || !hasMore || status !== "ready") return;
    busy.current = true;
    setAppending(true); setAppendError(false);
    try {
      const result = await requestBatch({ ...paramsRef.current, limit: CATALOGUE_BATCH_SIZE, offset: nextOffset });
      if (!alive.current) return;
      setData((previous) => previous ? { ...result, items: dedupe([...previous.items, ...result.items]) } : result);
      setNextOffset(result.items.length ? result.offset + result.items.length : result.total);
    } catch {
      if (alive.current) setAppendError(true);
    } finally {
      busy.current = false;
      if (alive.current) setAppending(false);
    }
  }, [hasMore, status, nextOffset]);
  useEffect(() => {
    if (!hasMore || appendError || appending || !sentinel.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) void loadMore();
    }, { rootMargin: "400px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, appendError, appending, loadMore]);
  const retry = () => { setStatus("loading"); setAttempt((n) => n + 1); };
  return { data, status, appending, appendError, hasMore, sentinel, loadMore, save, retry };
}
