"use client";

import { useEffect, useState } from "react";
import { trendingApi } from "@/lib/api/trending";
import type { BoardQuery, BoardResult } from "@/types/trending";

type BoardState =
  | { status: "loading" }
  | { status: "ready"; result: BoardResult }
  | { status: "error" };

const loading: BoardState = { status: "loading" };

export function useBoard({ platform, board }: BoardQuery) {
  const [attempt, setAttempt] = useState(0);
  const [entry, setEntry] = useState<{ key: string; state: BoardState }>();
  const key = `${platform}/${board}/${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    trendingApi.getBoard({ platform, board }, controller.signal).then(
      (result) => setEntry({ key, state: { status: "ready", result } }),
      () => {
        if (!controller.signal.aborted) setEntry({ key, state: { status: "error" } });
      },
    );
    return () => controller.abort();
  }, [platform, board, key]);

  return {
    state: entry?.key === key ? entry.state : loading,
    reload: () => setAttempt((current) => current + 1),
  };
}
