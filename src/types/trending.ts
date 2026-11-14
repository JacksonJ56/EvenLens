export type CategoryId = "general" | "tech" | "entertainment" | "community" | "finance" | "dev";

export type PlatformId =
  | "weibo" | "zhihu" | "baidu" | "ithome" | "hupu" | "bilibili"
  | "xiaohongshu" | "douyin" | "36kr" | "xueqiu" | "github" | "juejin";

export interface Board {
  id: string;
  label: string;
}

export interface Platform {
  id: PlatformId;
  name: string;
  boards: readonly [Board, ...Board[]];
  sourceUrl: (title: string) => string;
}

export interface Category {
  id: CategoryId;
  name: string;
  platforms: readonly [PlatformId, ...PlatformId[]];
}

export interface Trend {
  id: string;
  title: string;
  rank: number;
  url: string;
  platform: PlatformId;
  metric?: { value: string; label: string };
  status?: "hot" | "new" | "rising";
}

export interface BoardResult {
  items: Trend[];
  mode: "mock" | "live";
}

export interface BoardQuery {
  platform: PlatformId;
  board: string;
}
