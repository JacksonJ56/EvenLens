"use client";

import { useEffect, useRef, useState } from "react";
import { BoardUnavailable, trendingApi } from "@/lib/api/trending";
import type { BoardQuery, BoardResult } from "@/types/trending";

type BoardState =
  | { status: "loading" | "error" | "unavailable" }
  | { status: "ready"; result: BoardResult };

const loading: BoardState = { status: "loading" };

export interface BoardView {
  state: BoardState;
  refreshing: boolean;
  reload: () => void;
}

function boardKey({ platform, board }: BoardQuery) {
  return `${platform}/${board}`;
}

export function useBoard(query: BoardQuery | undefined) {
  const platform = query?.platform;
  const board = query?.board;
  const key = query ? boardKey(query) : undefined;
  const [retries, setRetries] = useState<Record<string, number>>({});
  const [entries, setEntries] = useState<Record<string, { state: BoardState; retry: number }>>({});
  const completed = useRef<Record<string, number>>({});
  const count = key ? retries[key] ?? 0 : 0;

  useEffect(() => {
    if (!platform || board === undefined || !key) return;
    const requestKey = key;
    const controller = new AbortController();

    function update(state: BoardState) {
      if (controller.signal.aborted) return;
      completed.current[requestKey] = count;
      setEntries((current) => {
        const previous = current[requestKey]?.state;
        const next: BoardState = state.status === "error" && previous?.status === "ready" && previous.result.mode === "live"
          ? { status: "ready", result: { ...previous.result, status: "stale" } }
          : state;
        return { ...current, [requestKey]: { state: next, retry: count } };
      });
    }

    const refresh = count > (completed.current[key] ?? 0);
    trendingApi.getBoard({ platform, board }, controller.signal, refresh).then(
      (result) => update({ status: "ready", result }),
      (error: unknown) => update({ status: error instanceof BoardUnavailable ? "unavailable" : "error" }),
    );
    return () => controller.abort();
  }, [platform, board, key, count]);

  function forQuery(target: BoardQuery): BoardView {
    const targetKey = boardKey(target);
    const entry = entries[targetKey];
    const attempt = retries[targetKey] ?? 0;
    const refreshing = targetKey === key && attempt > 0 && entry?.retry !== attempt;
    return {
      state: refreshing && entry?.state.status !== "ready" ? loading : entry?.state ?? loading,
      refreshing,
      reload: () => setRetries((current) => ({ ...current, [targetKey]: (current[targetKey] ?? 0) + 1 })),
    };
  }

  return { forQuery };
}
