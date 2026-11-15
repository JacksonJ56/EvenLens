import { mockBoard } from "@/mocks/trending";
import type { BoardQuery, BoardResult } from "@/types/trending";
import { delay } from "./delay";

export const trendingMode = process.env.NEXT_PUBLIC_TRENDING_MODE === "mock" ? "mock" : "live";

export class BoardUnavailable extends Error {}

export interface TrendingApi {
  getBoard(query: BoardQuery, signal?: AbortSignal, refresh?: boolean): Promise<BoardResult>;
}

export const trendingApi: TrendingApi = {
  async getBoard({ platform, board }, signal, refresh = false) {
    if (trendingMode === "mock") {
      await delay(280, signal);
      return { items: mockBoard({ platform, board }), mode: "mock" };
    }

    const path = `/api/boards/${encodeURIComponent(platform)}/${encodeURIComponent(board)}`;
    const response = await fetch(refresh ? `${path}?refresh=true` : path, { signal, cache: "no-store" });
    if (response.status === 404) throw new BoardUnavailable();
    if (!response.ok) throw new Error(`Board request failed (${response.status})`);
    const result: BoardResult = await response.json();
    if (result.mode !== "live" || !Array.isArray(result.items)) throw new Error("Invalid board response");
    return result;
  },
};
