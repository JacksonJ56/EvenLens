import type { Category, Platform, PlatformId } from "@/types/trending";
import type { Skill } from "@/types/agent";

function search(base: string) {
  return (title: string) => base + encodeURIComponent(title);
}

export const platforms: Record<PlatformId, Platform> = {
  weibo: { id: "weibo", name: "微博", boards: [{ id: "hot", label: "热搜榜" }, { id: "entertainment", label: "文娱榜" }, { id: "local", label: "同城榜" }], sourceUrl: search("https://s.weibo.com/weibo?q=") },
  zhihu: { id: "zhihu", name: "知乎", boards: [{ id: "hot", label: "热榜" }, { id: "tech", label: "科技话题" }], sourceUrl: search("https://www.zhihu.com/search?type=content&q=") },
  baidu: { id: "baidu", name: "百度", boards: [{ id: "hot", label: "热搜榜" }], sourceUrl: search("https://www.baidu.com/s?wd=") },
  ithome: { id: "ithome", name: "IT之家", boards: [{ id: "hot", label: "科技热榜" }], sourceUrl: search("https://dyn.ithome.com/search/?q=") },
  hupu: { id: "hupu", name: "虎扑", boards: [{ id: "hot", label: "社区热榜" }], sourceUrl: search("https://bbs.hupu.com/search?q=") },
  bilibili: { id: "bilibili", name: "哔哩哔哩", boards: [{ id: "hot", label: "热门视频" }], sourceUrl: search("https://search.bilibili.com/all?keyword=") },
  xiaohongshu: { id: "xiaohongshu", name: "小红书", boards: [{ id: "hot", label: "热门话题" }], sourceUrl: search("https://www.xiaohongshu.com/search_result?keyword=") },
  douyin: { id: "douyin", name: "抖音", boards: [{ id: "hot", label: "热点榜" }], sourceUrl: search("https://www.douyin.com/search/") },
  "36kr": { id: "36kr", name: "36氪", boards: [{ id: "hot", label: "商业热点" }], sourceUrl: search("https://36kr.com/search/articles/") },
  xueqiu: { id: "xueqiu", name: "雪球", boards: [{ id: "hot", label: "热门讨论" }], sourceUrl: search("https://xueqiu.com/k?q=") },
  github: { id: "github", name: "GitHub", boards: [{ id: "hot", label: "热门仓库" }, { id: "typescript", label: "TypeScript" }], sourceUrl: search("https://github.com/search?q=") },
  juejin: { id: "juejin", name: "掘金", boards: [{ id: "hot", label: "综合热榜" }, { id: "frontend", label: "前端" }], sourceUrl: search("https://juejin.cn/search?query=") },
};

export const categories: Category[] = [
  { id: "general", name: "综合", platforms: ["weibo", "zhihu", "baidu", "ithome", "hupu", "bilibili", "xiaohongshu", "douyin", "36kr"] },
  { id: "tech", name: "科技", platforms: ["ithome", "zhihu", "36kr", "bilibili"] },
  { id: "entertainment", name: "娱乐", platforms: ["bilibili", "weibo", "douyin", "xiaohongshu"] },
  { id: "community", name: "社区", platforms: ["hupu", "zhihu", "xiaohongshu", "bilibili"] },
  { id: "finance", name: "财经", platforms: ["36kr", "xueqiu", "baidu"] },
  { id: "dev", name: "开发", platforms: ["github", "juejin", "ithome"] },
];

export const skills: Skill[] = [
  { id: "timeline", label: "事件脉络重建", shortLabel: "脉络重建", placeholder: "想梳理哪个事件的时间线？" },
  { id: "context", label: "事件角色与背景分析", shortLabel: "角色与背景", placeholder: "想了解哪个事件的角色与背景？" },
  { id: "perspectives", label: "争议与观点梳理", shortLabel: "争议与观点", placeholder: "想梳理哪个事件的争议与观点？" },
];

export function getSkill(id?: Skill["id"]) {
  return skills.find((skill) => skill.id === id);
}
