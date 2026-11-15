import { mockBoard } from "@/mocks/trending";
import type { BoardQuery, BoardResult } from "@/types/trending";
import { delay } from "./delay";

export interface TrendingApi {
  getBoard(query: BoardQuery, signal?: AbortSignal): Promise<BoardResult>;
}

export const trendingApi: TrendingApi = {
  async getBoard(query, signal) {
    await delay(280, signal);
    return { items: mockBoard(query), mode: "mock" };
  },
};
