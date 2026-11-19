# EventLens · 事件透镜

EventLens 的首页热榜由 Next.js 前端、FastAPI 后端和独立 RSSHub 实例组成。对话继续使用已有的本地演示回复。

## 本地启动

需要 Node.js 20.9+、Python 3.11+。使用本机 RSSHub 时需要已启动的 Docker Desktop 或 Docker Engine。

从项目根目录启动 RSSHub。Compose 默认使用与 [HotPush](https://github.com/JackyST0/hotpush/blob/main/docker-compose.yml#L97-L110) 相同的 Chromium 镜像，供微博热搜等需要浏览器的路由使用。首次下载时间取决于网络。可通过 shell 的 `RSSHUB_IMAGE` 指定其他兼容镜像。

```bash
docker compose -f backend/compose.yaml up -d
```

第二个终端启动 FastAPI：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第三个终端启动前端。已有依赖时跳过 `npm ci`：

```bash
cd frontend
npm ci
cp .env.local.example .env.local
npm run dev
```

打开 http://localhost:3000。如端口已有程序，以 Next.js 输出的 `Local` 地址为准。配置已部署的 RSSHub 时，修改 `backend/.env` 中的 `RSSHUB_BASE_URL`，然后重启后端。

## 事件实验室 · 事件溯源

在 `backend/.env` 填写 `DEEPSEEK_API_KEY`。模型独立配置 `EVENT_TRACE_LLM_API_KEY`、`EVENT_TRACE_LLM_MODEL` 和 `EVENT_TRACE_LLM_BASE_URL`，地址填 OpenAI 兼容的 API 根路径，例如 DeepSeek 的 `https://api.deepseek.com/v1`，不要加 `/chat/completions`。所选模型需支持 JSON Object 模式。同一账户可以在两个变量分别配置凭据。所有凭据仅供 FastAPI 使用。改完重启后端。需要新增依赖时，在 `backend/` 运行 `python -m pip install -r requirements.txt`。

打开「事件实验室」，沿用已有的热点分区、平台、榜单和热点选择。单榜平台直接选热点，例如「综合 → 微博」。多榜平台先选榜单，例如「科技 → IT之家 → IT资讯最新」。在实验功能下拉选择「事件溯源」，点击「执行」。展开时间线节点可以看到详情、引文及原文入口。搜读受上游权限、站点访问策略和当前资料质量影响，结果可能标为「部分结果」，并列出资料缺口或补充搜索词。实验功能二、三仍为演示；实验室沿用真实榜单模式。

请求使用 `POST /api/event-trace`。同源 Next.js 路由通过 `EVENTLENS_BACKEND_URL` 转发，不受现有榜单代理的 30 秒默认超时限制。请求里的 `board_id` 代表显式选择的二级榜单，可以为 `null`；`feed_id` 始终标识真实榜单。后端在榜单快照中按 ID 查找热点，用快照覆盖浏览器提供的标题、原始链接、摘要和排名。若快照丢失或条目已经滚出榜单，需「刷新热点」后重选。

默认最多 3 轮，每轮最多 3 个搜索请求，每次最多返回 10 条；每个任务最多尝试读取 9 个网址，并发为 3。可用 `EVENT_TRACE_MAX_ROUNDS`、`EVENT_TRACE_MAX_QUERIES`、`DEEPSEEK_SEARCH_MAX_RESULTS`、`EVENT_TRACE_MAX_FETCH`、`EVENT_TRACE_PARALLEL` 调整。单次调用和任务总时限分别由 `EVENT_TRACE_CALL_TIMEOUT_SECONDS`、`EVENT_TRACE_TIMEOUT_SECONDS` 设置。短暂网络或限流错误最多重试一次。首次搜索全部失败时返回明确错误，后续搜索失败时可保留早前取得的证据。站点正文只能通过 [DeepSeek Fetch](https://api-docs.deepseek.com/api/fetch/) 取得，Fetch 不可用时按实际来源标注搜索片段或摘要。仓库测试替换的是外部 HTTP 响应，正常运行不加载测试数据。

| 实际文件与函数 | 输入、处理与下一步 |
| --- | --- |
| `frontend/src/components/layout/workspace.tsx` · `Workspace` | 首页导航维护 `categoryId`、`query`。打开实验室后，单独的 `labSelection` 保存分区、平台、榜单及选中的 `trendId`。 |
| `frontend/src/lib/event-lab.ts` · `resolveEventLabSource` → `frontend/src/hooks/use-board.ts` · `useBoard` | 从 `catalog.ts` 找到该分区的平台和榜单，再由现有榜单接口返回真实热点。选项变化时清理下游状态。 |
| `frontend/src/components/event-lab/event-lab-panel.tsx` · `EventLabPanel` / `submit` | 表单把 `trendId` 对应的 `Trend`、分区和榜单组合成 `context`，本地 `featureId` 指定功能。校验通过后交给 `useEventLabTask.run`。 |
| `frontend/src/hooks/use-event-lab-task.ts` · `run` → `frontend/src/lib/event-lab-features.ts` · 事件溯源的 `execute` | 锁定重复提交，创建取消信号。切换选择会终止前端旧请求，并隐藏旧结果；后端监听客户端断开。 |
| `frontend/src/lib/api/event-trace.ts` · `requestEventTrace` → `frontend/src/app/api/event-trace/route.ts` · `POST` | 组装所选热点和上下文 JSON。浏览器 `fetch("/api/event-trace")` 后，Next.js 将请求转发到 FastAPI 同名地址。 |
| `backend/app/event_trace/api.py` · `event_trace` / `canonical_event` | Pydantic 验证请求，根据快照核对热点，检查配置，再调用 `trace_graph.ainvoke`。 |
| `backend/app/event_trace/graph.py` · `prepare_event_node` / `plan_search_node` | 准备 `event_context`，用固定提示词和独立模型生成 Pydantic `SearchPlan`。 |
| `backend/app/event_trace/graph.py` · `search_node` / `fetch_node` → `backend/app/event_trace/clients.py` · `TraceClients.search` / `fetch` | 直接 HTTP 调用 DeepSeek。每轮词保存在 `search_queries`，累计内容按 URL 去重后保存在 `sources`，抓取状态和正文也随来源保存。抓取前校验公网地址。 |
| `backend/app/event_trace/graph.py` · `evaluate_node` / `after_evaluate` | 让模型检查指向与资料缺口，有未搜索过的补充词且未用完轮数时回到 `search_node`。 |
| `backend/app/event_trace/graph.py` · `extract_node` / `validate_node` / `sort_node` → `backend/app/event_trace/timeline.py` | 模型给出候选节点，Python 查纯文本引文及来源 ID、合并匹配节点、标记时间冲突并按日期排序。引文存在不等于独立事实核验。 |
| `backend/app/event_trace/schemas.py` · `EventTraceResponse` → `frontend/src/components/event-lab/event-trace-timeline.tsx` · `EventTraceTimeline` | API 返回 `trace_id`、`selection`、`selected_event`、`subject`、`status`、搜索历史、`timeline`、`sources`、`missing_aspects`、`suggested_queries` 和 `warnings`。结果窗口把 JSON 渲染为可展开的时间线。 |

## 榜单配置与接口

- `backend/boards.json` 用 `平台 ID/榜单 ID` 对应数据源，与 `frontend/src/lib/catalog.ts` 的 ID 一致。`route` 指向本机 RSSHub，`url` 指向公开 HTTPS 榜单。多个 `sources` 按顺序尝试，`sourceTitle` 显示实际返回数据的来源。RSSHub 地址、默认刷新周期、每个来源的请求超时与配置文件位置可在 `backend/.env` 中修改。
- `GET /api/boards/{platform}/{board}` 返回按上游顺序排列的 `items`、`mode: "live"`、`status`、`updatedAt` 和 `sourceTitle`。Next.js 将同源请求转发到 `EVENTLENS_BACKEND_URL`。
- 后端在榜单首次访问时拉取，随后定期刷新已访问的榜单。以今日热榜为唯一来源的榜单每 15 分钟安排一次自动拉取。刷新按钮使用 `?refresh=true` 发起一次拉取。所有来源都失败时返回进程内的上次成功快照，状态为 `stale`，时间保持为上次成功时间。重启后缓存需要重建。无可用数据时返回 503，未配置榜单返回 404，有效的空榜返回 200 和空数组。
- 热度只在源提供相应字段时显示。RSS 可配置 `metric_field`（RSS 元素名，命名空间使用 `{URI}name`）和 `metric_label`。阅读区可显示来源提供的摘要，原文入口跳往条目所属平台。
- 设置 `frontend/.env.local` 中的 `NEXT_PUBLIC_TRENDING_MODE=mock` 并重启前端，可切换到明确标记的演示模式。真实模式在请求失败时继续显示错误或旧的真实数据。

## 榜单来源及验证

页面由 `frontend/src/lib/catalog.ts` 为每个分类分别指定平台和分榜。`backend/boards.json` 记录请求地址和备用源。表中的条目数是本地实际请求取得的结果，源更新后数量可能变化。

| 分类 | 平台与榜单 | 实测数据源 | 实测条目数 |
| --- | --- | --- | --- |
| 综合 | 微博 · 热搜 | 微博公开热搜接口，RSSHub 首选路由失败时接管 | 50 |
| 综合 | 小红书 · 阅读榜、点赞榜、收藏榜（均为近 3 天） | 今日热榜的 `read-3d`、`like-3d`、`collect-3d` | 各 20 |
| 综合 | 抖音 · 热榜 | 抖音公开热点接口 | 49 |
| 综合 | 知乎 · 热议 | RSSHub `/zhihu/hot`，知乎官方热榜接口兜底 | 30 |
| 综合 | 百度 · 热搜 | RSSHub `/baidu/top`，百度官方实时热搜榜兜底 | 50 |
| 综合 | 央视新闻 · 新闻滚动 | RSSHub `/cctv/news`，央视网新闻滚动接口兜底 | 50 |
| 综合 | 联合早报 · 本土最新、国际最新 | RSSHub `/zaobao/realtime/singapore`、`/zaobao/realtime/world`，官网页面兜底 | 各 24 |
| 综合 | China Daily · Home News | 英文官网首页新闻 | 33 |
| 综合 | 百度贴吧 · 热榜 | 今日热榜的贴吧热门话题 | 20 |
| 科技 | IT之家 · IT资讯最新、业界、网络 | IT之家官网 `it.ithome.com` 三个原栏目 | 11、5、30 |
| 科技 | 哔哩哔哩 · 科技数码 | RSSHub `/bilibili/ranking/tech`、官方榜单接口、全网热点数码科技分榜 | 50 |
| 科技 | 少数派 · 热门内容 | 今日热榜 · 少数派最热 | 20 |
| 科技 | 机器之心 · 最新 | 今日热榜 · 机器之心文章库 | 20 |
| 科技 | 虎嗅 · 热文、最新 | 今日热榜对应分榜 | 8、20 |
| 科技 | 電獺少女 · 最新文章（默认） | 官方网站最新文章列表 | 21 |
| 科技 | 36氪 · 热榜、最新 | RSSHub `/36kr/hot-list`、今日热榜最新。热榜的今日热榜备用源也已验证 | 8、20 |
| 娱乐 | 微博 · 文娱 | 今日热榜 · 微博文娱 | 20 |
| 娱乐 | 哔哩哔哩 · 娱乐 | RSSHub `/bilibili/ranking/ent`、官方榜单接口、全网热点娱乐分榜 | 50 |
| 娱乐 | 豆瓣书影音 · 电影、电视、读书、音乐 | 今日热榜对应分榜 | 10、10、20、20 |
| 娱乐 | 红果短剧 · 热播榜、真人剧、AI剧、漫剧 | 今日热榜对应分榜，链接指向红果官网详情 | 各 20 |
| 娱乐 | 游民星空 · 今日推荐 | 今日热榜对应分榜 | 20 |
| 社区 | 豆瓣社区 · 精选讨论、热门话题、发现小组 | 今日热榜对应分榜 | 各 20 |
| 社区 | 虎扑 · 步行街、NBA、游戏、数码、影视娱乐、国际足球 | 今日热榜对应分榜 | 各 20 |
| 财经 | 同花顺 · 头条（默认） | 今日热榜 · 同花顺头条 | 20 |
| 财经 | 东方财富 · 财经要闻（默认） | 东方财富财经要闻页 | 50 |
| 财经 | 华尔街见闻 · 最热（当日）、最新 | RSSHub `/wallstreetcn/hot`、`/wallstreetcn/news`，最热只读取官方接口的当日榜数据，最新有今日热榜兜底 | 10、30 |
| 开发 | GitHub · 今日热门仓库 | GitHub 官方 `/trending` | 15 |
| 开发 | Hugging Face · 技术文章、社区热文、热门模型 | 官方博客 RSS、今日热榜社区热文、官方 Trending 模型 API | 50、20、20 |
| 开发 | 吾爱破解 · 今日、本周、本月 | 今日热榜对应分榜 | 各 15 |
| 开发 | InfoQ · 7 天、1 个月、6 个月 | 今日热榜 `day`、`month`、`year` 对应页面，周期与 InfoQ 公开站点的热点选项一致 | 各 20 |

央视新闻客户端的「时讯24小时」尚未找到可验证的公开榜单。综合分类使用央视网的「新闻滚动」栏目。小红书的近 3 天指榜单的统计周期，原帖的发布日期可以更早。InfoQ 备用来源页面的 `year` 标识对应页面明示的 6 个月榜。

## 开发验证

- 在 `backend/` 运行 `python -m unittest discover -s tests -v`。
- 在 `frontend/` 运行 `npm run typecheck` 和 `npm run build`。
- 后续如需正文，后端可在 `Trend.preview.blocks` 中提供 `paragraph` 或 `image`。只有摘要时填写 `Trend.preview.summary`。阅读区按实际取得的字段展示。
# 公众舆情分析（第二个实验功能）

已接入现有事件实验室的「公众舆情分析」，复用热点级联选择。支持后台任务、平台能力校验、授权评论 JSON/CSV 导入、两个 Deep Agent、分批分析、来源引用及结构化报告。在线采集需要单独安装 MediaCrawler 并配置适用授权和合法平台会话；没有数据时不会用演示结果填充。

新增后端依赖后请重新安装 `backend/requirements.txt` 并重启 FastAPI。详细启动方式、PostgreSQL、环境变量、接口、逐文件调用链和验证边界见 [公众舆情功能说明](backend/PUBLIC_OPINION.md)；评论文件字段见 [导入格式](frontend/public/public-opinion-import.md)。
