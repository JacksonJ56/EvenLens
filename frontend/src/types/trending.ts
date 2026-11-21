export type CategoryId = "general" | "tech" | "entertainment" | "community" | "finance" | "dev";

export type PlatformId =
  | "weibo" | "zhihu" | "baidu" | "ithome" | "hupu" | "bilibili"
  | "xiaohongshu" | "douyin" | "36kr" | "xueqiu" | "github" | "juejin"
  | "cctv" | "zaobao" | "chinadaily" | "tieba" | "sspai" | "jiqizhixin" | "huxiu" | "agirls"
  | "douban-media" | "hongguo" | "gamersky" | "douban-community" | "tonghuashun" | "eastmoney"
  | "wallstreetcn" | "huggingface" | "52pojie" | "infoq";

export interface Board {
  id: string;
  label: string;
}

export interface Platform {
  id: PlatformId;
  name: string;
  sourceUrl: (title: string) => string;
}

export interface CategoryPlatform {
  id: PlatformId;
  boards: readonly [Board, ...Board[]];
}

export interface Category {
  id: CategoryId;
  name: string;
  platforms: readonly [CategoryPlatform, ...CategoryPlatform[]];
}

export interface Trend {
  id: string;
  title: string;
  rank: number;
  url: string;
  platform: PlatformId;
  metric?: { value: string; label: string };
  status?: "hot" | "new" | "rising";
  preview?: {
    summary?: string;
  };
}

export interface BoardResult {
  items: Trend[];
  mode: "mock" | "live";
  status?: "fresh" | "stale";
  updatedAt?: string;
  sourceTitle?: string;
}

export interface BoardQuery {
  platform: PlatformId;
  board: string;
}
