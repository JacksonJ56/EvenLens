"use client";

import { useEffect, useRef, useState } from "react";
import { BoardUnavailable, trendingApi } from "@/lib/api/trending";
import type { BoardQuery, BoardResult } from "@/types/trending";

type BoardState =
  | { status: "loading" | "error" | "unavailable" }
  | { status: "ready"; result: BoardResult };

const loading: BoardState = { status: "loading" };

export function useBoard({ platform, board }: BoardQuery) {
  const key = `${platform}/${board}`;
  const [retries, setRetries] = useState<Record<string, number>>({});
  const [entries, setEntries] = useState<Record<string, { state: BoardState; retry: number }>>({});
  const completed = useRef<Record<string, number>>({});
  const count = retries[key] ?? 0;
  const entry = entries[key];

  useEffect(() => {
    const controller = new AbortController();

    function update(state: BoardState) {
      if (controller.signal.aborted) return;
      completed.current[key] = count;
      setEntries((current) => {
        const previous = current[key]?.state;
        const next: BoardState = state.status === "error" && previous?.status === "ready" && previous.result.mode === "live"
          ? { status: "ready", result: { ...previous.result, status: "stale" } }
          : state;
        return { ...current, [key]: { state: next, retry: count } };
      });
    }

    const refresh = count > (completed.current[key] ?? 0);
    trendingApi.getBoard({ platform, board }, controller.signal, refresh).then(
      (result) => update({ status: "ready", result }),
      (error: unknown) => update({ status: error instanceof BoardUnavailable ? "unavailable" : "error" }),
    );
    return () => controller.abort();
  }, [platform, board, key, count]);

  const refreshing = count > 0 && entry?.retry !== count;
  return {
    state: refreshing && entry?.state.status !== "ready" ? loading : entry?.state ?? loading,
    refreshing,
    reload: () => setRetries((current) => ({ ...current, [key]: (current[key] ?? 0) + 1 })),
  };
}
