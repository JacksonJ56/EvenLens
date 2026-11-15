import type { Category, CategoryPlatform, Platform, PlatformId } from "@/types/trending";
import type { Skill } from "@/types/agent";

function search(base: string) {
  return (title: string) => base + encodeURIComponent(title);
}

export const platforms: Record<PlatformId, Platform> = {
  weibo: { id: "weibo", name: "微博", sourceUrl: search("https://s.weibo.com/weibo?q=") },
  zhihu: { id: "zhihu", name: "知乎", sourceUrl: search("https://www.zhihu.com/search?type=content&q=") },
  baidu: { id: "baidu", name: "百度", sourceUrl: search("https://www.baidu.com/s?wd=") },
  ithome: { id: "ithome", name: "IT之家", sourceUrl: search("https://dyn.ithome.com/search/?q=") },
  hupu: { id: "hupu", name: "虎扑", sourceUrl: search("https://bbs.hupu.com/search?q=") },
  bilibili: { id: "bilibili", name: "哔哩哔哩", sourceUrl: search("https://search.bilibili.com/all?keyword=") },
  xiaohongshu: { id: "xiaohongshu", name: "小红书", sourceUrl: search("https://www.xiaohongshu.com/search_result?keyword=") },
  douyin: { id: "douyin", name: "抖音", sourceUrl: search("https://www.douyin.com/search/") },
  "36kr": { id: "36kr", name: "36氪", sourceUrl: search("https://36kr.com/search/articles/") },
  xueqiu: { id: "xueqiu", name: "雪球", sourceUrl: search("https://xueqiu.com/k?q=") },
  github: { id: "github", name: "GitHub", sourceUrl: search("https://github.com/search?q=") },
  juejin: { id: "juejin", name: "掘金", sourceUrl: search("https://juejin.cn/search?query=") },
  "cctv": { id: "cctv", name: "央视新闻", sourceUrl: () => "https://news.cctv.com/" },
  "zaobao": { id: "zaobao", name: "联合早报", sourceUrl: () => "https://www.zaobao.com.sg/" },
  "chinadaily": { id: "chinadaily", name: "中国日报 China Daily", sourceUrl: () => "https://www.chinadaily.com.cn/" },
  "tieba": { id: "tieba", name: "百度贴吧", sourceUrl: () => "https://tieba.baidu.com/" },
  "sspai": { id: "sspai", name: "少数派", sourceUrl: () => "https://sspai.com/" },
  "jiqizhixin": { id: "jiqizhixin", name: "机器之心", sourceUrl: () => "https://www.jiqizhixin.com/" },
  "huxiu": { id: "huxiu", name: "虎嗅", sourceUrl: () => "https://www.huxiu.com/" },
  "agirls": { id: "agirls", name: "電獺少女", sourceUrl: () => "https://agirls.aotter.net/" },
  "douban-media": { id: "douban-media", name: "豆瓣书影音", sourceUrl: () => "https://www.douban.com/" },
  "hongguo": { id: "hongguo", name: "红果短剧", sourceUrl: () => "https://hongguoduanju.com/" },
  "gamersky": { id: "gamersky", name: "游民星空", sourceUrl: () => "https://www.gamersky.com/" },
  "douban-community": { id: "douban-community", name: "豆瓣社区", sourceUrl: () => "https://www.douban.com/group/" },
  "tonghuashun": { id: "tonghuashun", name: "同花顺", sourceUrl: () => "https://news.10jqka.com.cn/" },
  "eastmoney": { id: "eastmoney", name: "东方财富", sourceUrl: () => "https://finance.eastmoney.com/" },
  "wallstreetcn": { id: "wallstreetcn", name: "华尔街见闻", sourceUrl: () => "https://wallstreetcn.com/" },
  "huggingface": { id: "huggingface", name: "Hugging Face", sourceUrl: () => "https://huggingface.co/" },
  "52pojie": { id: "52pojie", name: "吾爱破解", sourceUrl: () => "https://www.52pojie.cn/" },
  "infoq": { id: "infoq", name: "InfoQ", sourceUrl: () => "https://www.infoq.cn/" },
};

function pick(id: PlatformId, [board, label]: [string, string], ...rest: [string, string][]): CategoryPlatform {
  return { id, boards: [{ id: board, label }, ...rest.map(([id, label]) => ({ id, label }))] };
}

export const categories: Category[] = [
  { id: "general", name: "综合", platforms: [
    pick("weibo", ["hot", "热搜"]),
    pick("xiaohongshu", ["reads-3d", "阅读榜（近 3 天）"], ["likes-3d", "点赞榜（近 3 天）"], ["collections-3d", "收藏榜（近 3 天）"]),
    pick("douyin", ["hot", "热榜"]),
    pick("zhihu", ["hot", "热议"]),
    pick("baidu", ["hot", "热搜"]),
    pick("cctv", ["news", "新闻滚动"]),
    pick("zaobao", ["singapore", "本土最新"], ["world", "国际最新"]),
    pick("chinadaily", ["home-news", "Home News"]),
    pick("tieba", ["hot", "热榜"]),
  ] },
  { id: "tech", name: "科技", platforms: [
    pick("ithome", ["latest", "IT资讯最新"], ["industry", "业界"], ["network", "网络"]),
    pick("bilibili", ["tech", "科技数码"]),
    pick("sspai", ["hottest", "热门内容"]),
    pick("jiqizhixin", ["latest", "最新"]),
    pick("huxiu", ["hot", "热文"], ["latest", "最新"]),
    pick("agirls", ["latest", "最新文章"]),
    pick("36kr", ["hot", "热榜"], ["latest", "最新"]),
  ] },
  { id: "entertainment", name: "娱乐", platforms: [
    pick("weibo", ["entertainment", "文娱"]),
    pick("bilibili", ["entertainment", "娱乐"]),
    pick("douban-media", ["movie", "电影"], ["tv", "电视"], ["book", "读书"], ["music", "音乐"]),
    pick("hongguo", ["hot", "热播榜"], ["live-action", "真人剧"], ["ai", "AI剧"], ["animation", "漫剧"]),
    pick("gamersky", ["recommend", "今日推荐"]),
  ] },
  { id: "community", name: "社区", platforms: [
    pick("douban-community", ["discussion", "精选讨论"], ["topic", "热门话题"], ["group", "发现小组"]),
    pick("hupu", ["gambia", "步行街"], ["nba", "NBA"], ["games", "游戏"], ["digital", "数码"], ["entertainment", "影视娱乐"], ["soccer", "国际足球"]),
  ] },
  { id: "finance", name: "财经", platforms: [
    pick("tonghuashun", ["headlines", "头条"]),
    pick("eastmoney", ["latest", "财经要闻"]),
    pick("wallstreetcn", ["hot", "最热（当日）"], ["latest", "最新"]),
  ] },
  { id: "dev", name: "开发", platforms: [
    pick("github", ["hot", "今日热门仓库"]),
    pick("huggingface", ["blog", "技术文章"], ["community", "社区热文"], ["models", "热门模型"]),
    pick("52pojie", ["today", "今日"], ["weekly", "本周"], ["monthly", "本月"]),
    pick("infoq", ["7d", "7天"], ["1m", "1个月"], ["6m", "6个月"]),
  ] },
];

export const skills: Skill[] = [
  { id: "timeline", label: "事件脉络重建", shortLabel: "脉络重建", placeholder: "想梳理哪个事件的时间线？" },
  { id: "context", label: "事件角色与背景分析", shortLabel: "角色与背景", placeholder: "想了解哪个事件的角色与背景？" },
  { id: "perspectives", label: "争议与观点梳理", shortLabel: "争议与观点", placeholder: "想梳理哪个事件的争议与观点？" },
];

export function getSkill(id?: Skill["id"]) {
  return skills.find((skill) => skill.id === id);
}
