import type { BoardQuery, CategoryId, Trend } from "./trending";

export interface EventLabSelection {
  categoryId?: CategoryId;
  platformId?: BoardQuery["platform"];
  boardId?: BoardQuery["board"];
  trendId?: Trend["id"];
}

export interface EventLabEventContext {
  categoryId: CategoryId;
  categoryName: string;
  platformId: Trend["platform"];
  platformName: string;
  feedId: BoardQuery["board"];
  boardId?: BoardQuery["board"];
  boardName?: string;
  capturedAt?: string;
  trendId: Trend["id"];
  title: Trend["title"];
  url?: Trend["url"];
  trend: Trend;
}
