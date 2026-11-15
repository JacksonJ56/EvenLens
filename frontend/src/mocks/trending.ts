import { platforms } from "@/lib/catalog";
import type { BoardQuery, Trend } from "@/types/trending";

type Sample = readonly [title: string, metric?: string, status?: Trend["status"], url?: string];

const samples: Record<string, readonly Sample[]> = {
  "weibo/hot": [
    ["多地迎来本年度首轮秋日观鸟季", "184.6万", "hot"],
    ["城市公共空间可以怎样延长开放时间", "152.3万", "new"],
    ["年轻人开始流行交换周末路线", "128.5万", "rising"],
    ["国产动画新作公布首支预告", "96.2万", "hot"],
    ["高校图书馆试点向社区居民开放", "82.4万", "new"],
    ["一张图看懂个人碳账户如何使用", "71.8万"],
    ["越来越多的博物馆推出夜游场次", "65.3万", "rising"],
    ["通勤时你会选择听播客还是听音乐", "58.9万"],
    ["秋日第一批候鸟抵达城市湿地", "42.6万"],
    ["社区食堂开始尝试小份菜套餐", "36.1万"],
    ["独立书店联合发起图书交换活动", "32.8万"],
    ["周末骑行路线如何避开车流高峰", "26.4万"],
    ["看展时你会提前做功课吗", "21.6万"],
    ["阳台种植新手从什么植物开始", "18.5万"],
  ],
  "weibo/entertainment": [
    ["国产动画新作公布首支预告", "96.2万", "hot"],
    ["周末短片展首次增设观众投票", "55.6万", "new"],
    ["这部科幻电影的配乐用到了哪些乐器", "41.3万"],
    ["舞台剧巡演开放幕后探班活动", "30.7万"],
    ["独立乐队发布全新现场录音", "18.9万"],
  ],
  "weibo/local": [],
  "zhihu/hot": [
    ["如何设计一个真正好用的社区图书馆？", "320万", "hot"],
    ["哪些常用的统计图最容易被误读？", "186万", "new"],
    ["为什么有些城市的夜间步行体验更好？", "115万"],
    ["人们怎样形成对一座陌生城市的印象？", "84万"],
    ["你会如何安排一整天的离线生活？", "58万"],
  ],
  "zhihu/tech-top-answers": [
    ["端侧模型的性能应该如何衡量？", "128万"],
    ["开源项目如何管理向后兼容？", "96万"],
    ["为什么电纸书刷新时会出现残影？", "61万"],
    ["怎样比较不同的向量检索方法？", "34万"],
  ],
  "baidu/hot": [
    ["城市慢行地图新增无障碍路线", "452万", "hot"],
    ["秋日赏叶路线推荐", "336万"],
    ["社区家庭急救体验课开放报名", "281万", "new"],
    ["公共自行车站点调整指南", "214万"],
    ["线上展览怎么看更方便", "108万"],
  ],
  "ithome/hot": [
    ["国产开源桌面系统发布测试版", "245", "new"],
    ["新款电子墨水屏设备支持局部刷新", "188", "hot"],
    ["轻量化本地模型工具开放试用", "156", "rising"],
    ["桌面系统文件搜索功能迎来更新", "108"],
    ["可拆卸电池设计受到更多关注", "83"],
    ["如何为家庭服务器挑选低功耗硬件", "42"],
  ],
  "hupu/hot": [
    ["主队输赢之外，球迷最看重什么", "318", "hot"],
    ["周末篮球场组队攻略", "205", "new"],
    ["从新秀赛季到成为球队核心有哪些变化", "184"],
    ["第一次参加城市路跑应该注意什么", "119"],
    ["你最喜欢的球馆观赛视角", "82"],
  ],
  "bilibili/popular": [
    ["在家搭一座小型气象站", "76.1万", "rising"],
    ["一分钟看完老相机的机械结构", "63.2万", "hot"],
    ["把城市夜景画进速写本", "43.9万"],
    ["用三种材料复刻童年手工玩具", "31.7万"],
    ["在城市屋顶观察一整晚的星空", "26.8万"],
  ],
  "bilibili/hot-search": [
    ["一分钟看完老相机的机械结构"],
    ["在城市屋顶观察一整晚的星空"],
    ["在家搭一座小型气象站"],
  ],
  "xiaohongshu/likes-3d": [
    ["秋天的公园散步路线", undefined, "new"],
    ["周末书店地图", undefined, "hot"],
    ["一周便当如何提前准备", undefined, "rising"],
    ["小户型客厅的阅读角改造"],
    ["只带一个背包的短途旅行清单"],
  ],
  "douyin/hot": [
    ["街角小店的第一杯秋日热饮", "381万", "hot"],
    ["非遗木雕的一天", "275万", "new"],
    ["和城市跑团一起看日出", "198万"],
    ["给老家巷子拍一部微纪录片", "120万"],
  ],
  "36kr/hot": [
    ["小型创业团队如何衡量 AI 工具投入", undefined, "hot"],
    ["社区零售探索更灵活的门店模型"],
    ["工业软件企业如何做好第一批客户服务", undefined, "new"],
    ["户外品牌开始关注城市通勤市场"],
    ["线下展览如何找到稳定的复购场景"],
  ],
  "xueqiu/topics": [
    ["如何读懂企业现金流量表", "129", "hot"],
    ["跟踪行业景气度需要看哪些指标", "92"],
    ["不同分红频率会怎样影响长期收益", "65"],
    ["财报里的合同负债应当如何理解", "58"],
  ],
  "github/hot": [
    ["vercel/next.js", "示例 +210", "rising", "https://github.com/vercel/next.js"],
    ["langchain-ai/langgraph", "示例 +142", "hot", "https://github.com/langchain-ai/langgraph"],
    ["vitejs/vite", "示例 +98", undefined, "https://github.com/vitejs/vite"],
    ["pallets/flask", "示例 +63", undefined, "https://github.com/pallets/flask"],
  ],
  "github/typescript": [
    ["microsoft/TypeScript", "示例 +132", "hot", "https://github.com/microsoft/TypeScript"],
    ["shadcn-ui/ui", "示例 +121", "rising", "https://github.com/shadcn-ui/ui"],
    ["tanstack/query", "示例 +46", undefined, "https://github.com/TanStack/query"],
  ],
  "juejin/hot": [
    ["从界面状态到请求缓存，如何划分前端职责？", "176", "hot"],
    ["构建一个可以取消的任务队列", "143", "new"],
    ["怎样写出便于维护的类型定义", "81"],
    ["服务端渲染的排查笔记", "72"],
  ],
  "juejin/frontend": [
    ["用 CSS 实现可访问的响应式布局", "136", "new"],
    ["React 中如何保留编辑状态", "103", "hot"],
    ["理解流式渲染的边界和回退", "85"],
  ],
};

const sampleAliases: Record<string, string> = {
  "ithome/latest": "ithome/hot",
  "bilibili/tech": "bilibili/popular",
  "xiaohongshu/reads-3d": "xiaohongshu/likes-3d",
  "hupu/gambia": "hupu/hot",
};

const metricLabels: Partial<Record<BoardQuery["platform"], string>> = {
  weibo: "热度", zhihu: "热度", baidu: "热度", ithome: "评论", hupu: "回复",
  bilibili: "播放", douyin: "热度", xueqiu: "讨论", github: "Stars", juejin: "点赞",
};

export function mockBoard({ platform, board }: BoardQuery): Trend[] {
  const key = `${platform}/${board}`;
  const entries = samples[sampleAliases[key] ?? key] ?? [];
  return entries.map(([title, value, status, url], index) => ({
    id: `${key}/${index + 1}`,
    title,
    rank: index + 1,
    url: url ?? platforms[platform].sourceUrl(title),
    platform,
    status,
    metric: value ? { value, label: metricLabels[platform] ?? "" } : undefined,
  }));
}
