"use client";
import { useCallback, useEffect, useState } from "react";

// Coalesce concurrent mounts (including React Strict Mode), without retaining
// stale responses. Retrying or revisiting still asks the public API afresh.
const subscribers = new Map<() => Promise<unknown>, number>();
const inFlight = new Map<() => Promise<unknown>, Promise<unknown>>();
export function usePublicResource<T>(loader: () => Promise<T>) {
  const [state, setState] = useState<{ status: "loading" | "ready" | "error"; data: T | null }>({ status: "loading", data: null });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    subscribers.set(loader, (subscribers.get(loader) ?? 0) + 1);
    let request = inFlight.get(loader) as Promise<T> | undefined;
    if (!request) {
      request = loader();
      inFlight.set(loader, request);
      const clear = () => { if (inFlight.get(loader) === request) inFlight.delete(loader); };
      request.then(clear, clear);
    }
    request.then((data) => { if (active) setState({ status: "ready", data }); }, () => { if (active) setState({ status: "error", data: null }); });
    return () => {
      active = false;
      subscribers.set(loader, (subscribers.get(loader) ?? 1) - 1);
      queueMicrotask(() => {
        if (!subscribers.get(loader)) { inFlight.delete(loader); subscribers.delete(loader); }
      });
    };
  }, [loader, attempt]);
  const retry = useCallback(() => { setState({ status: "loading", data: null }); setAttempt((n) => n + 1); }, []);
  return { ...state, retry };
}
