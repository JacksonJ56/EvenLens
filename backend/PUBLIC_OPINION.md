# EventLens 公众舆情分析 · 实现与使用

当前支持配置为微博、小红书、抖音、快手、哔哩哔哩、百度贴吧六个平台；各平台的实际采集条件仍以能力接口、运行环境与授权状态为准。知乎仅保留热榜与事件溯源，不支持公众舆情分析，在该功能的平台下拉栏中置灰。

2026-11-20 移除范围：知乎舆情平台/搜索/帖子映射、评论采集、正文阅读、登录验证、专用浏览器快照及访问预检查代码，以及专用环境变量和已退役功能的测试。共用分析、其他平台登录、授权导入、小红书阅读和 DNS 故障切换保留。新建任务、导入及历史任务恢复均先做平台校验；知乎返回422，已有任务与报告不删除。独立 MediaCrawler 仓库不修改。

前端复用后端 `/capabilities` 与现有 SpringDropdown 禁用逻辑，不维护第二套支持列表。选中知乎后从事件溯源切到公众舆情时，保留当前选择、标红提示并禁止执行；切回事件溯源即可继续选择知乎。鼠标和键盘均不能在舆情功能下选中知乎。

移除验收：122项后端测试、TypeScript检查、Next.js生产构建通过；真实前端代理返回的能力列表不再含知乎，知乎登录接口返回422。浏览器回归验证灰色样式、鼠标/键盘禁用、功能切换、其他平台登录/取消/验证、授权导入、错误重试和移动端；未创建真实Agent任务。同步修正Motion内联透明度覆盖CSS禁用样式的问题。已清理该功能保存的知乎Cookie配置与专用快照，其他平台凭据和历史任务保留。

这是现有实验室的第二个功能，不是聊天输入页。第一个「事件溯源」的 API、图和提示词没有被替换，第三个演示入口保留。

## 当前完成程度

已经实现：复用级联选择、统一平台能力校验、JSON/CSV 授权评论导入、持久化后台任务、查询/取消/重试恢复、两个独立 Deep Agent、LangGraph 固定流程、按来源顺序截取评论、分批语义分析与缓存、程序统计、节日日历与外部语境研究、引用校验、动态报告和评论原文按需读取。

公众舆情分析现支持六个平台，不代表均已实采成功。知乎不再支持此功能，保留其热榜与事件溯源。MediaCrawler 未配置合法会话时，API 返回明确的 503；导入路径仍可使用。没有搜索或评论结果时不会填充演示资料。

## 启动

项目根目录运行；保留现有 `backend/.env`，只添加需要的变量，不要用示例文件覆盖现有密钥。

```sh
cd backend
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```sh
cd frontend
npm ci
npm run dev
```

前端默认访问 3000，服务端代理访问 `http://127.0.0.1:8000`；需要改后端端口时在 `frontend/.env.local` 设置 `EVENTLENS_BACKEND_URL` 并重启 Next.js。密钥只在后端。普通任务请求马上返回 202，浏览器每秒查询真实状态，不让一个长 HTTP 请求等待整个分析。

## 数据库

持久化层使用 SQLAlchemy，支持 PostgreSQL + psycopg；本地未配置数据库时使用 `backend/app/data/public_opinion.sqlite3`，避免新增功能使原热榜启动依赖 PostgreSQL。该目录被 Git 忽略。

PostgreSQL 开发服务已加入现有 Compose 的可选 `opinion` profile，不改变 RSSHub：

```sh
cd backend
docker compose --profile opinion up -d postgres
```

仅绑定 `127.0.0.1:5433`。默认开发账号/库为 `eventlens`，默认密码 `eventlens-local-development`，部署时应通过 `EVENTLENS_POSTGRES_PASSWORD` 设置自己的密码。在后端 `.env` 设置匹配的连接串后重启：

```env
PUBLIC_OPINION_DATABASE_URL=postgresql+psycopg://eventlens:eventlens-local-development@127.0.0.1:5433/eventlens
```

不要把生产数据库暴露到公网。MVP 没有新增用户系统，数据接口面向本地研究场景；多用户部署前需补鉴权与数据隔离。

自动建立以下表（此模块首次引入，无旧表迁移）：

| 表 | 内容 |
| --- | --- |
| opinion_tasks | 不可变选择快照、幂等键、状态、阶段检查点、用量 |
| opinion_task_events | 真正进入过的步骤及时间，用于前端进度记录 |
| opinion_datasets | 数据集绑定、帖子元数据、数据概况 |
| opinion_comments | 原始序号、帖子/评论 ID、清洗正文、原始正文、时间和来源 |
| opinion_analysis_cache | 模型/提供方、Prompt 版本、任务、批次内容哈希对应结果 |
| opinion_external_sources | 宏观检索资料与已读取的有限正文快照 |
| opinion_reports | 最终 Pydantic 报告 JSON |

使用单个 FastAPI worker。最多同时执行 2 个任务、排队和执行合计最多 10 个。服务重启将未完成任务标为 interrupted；调用恢复接口会跳过已经保存的业务阶段，未完成的 Agent 阶段重新执行，批次缓存可复用。**这不是任意模型调用位置的精确 LangGraph checkpointer 恢复，也不是多进程队列。** 每次模型调用都会保存用量预算，恢复不会自动重置预算。

## API

全部位于 `/api/public-opinion`：

| 方法/路径 | 输入/输出 |
| --- | --- |
| GET /capabilities | 六个平台的理论支持、adapter 实现状态、采集配置状态和原因 |
| POST /datasets/import | `ImportRequest`：selection、event、format、content、authorized=true；返回 dataset_id、stats、binding |
| POST /tasks | `OpinionRequest`：function_id=public_opinion、selection、event、可选 dataset_id、idempotency_key；返回任务，202 |
| GET /tasks/{id} | 真实 status、stage、message、history 和模型用量 |
| DELETE /tasks/{id} | 取消任务和正在运行的子进程 |
| POST /tasks/{id}/resume | 恢复失败/取消/中断任务，不替换原始事件快照 |
| GET /tasks/{id}/report | `OpinionReport`；未完成为 409 |
| GET /tasks/{id}/comments?post_id=...&comment_id=... | 当前任务所引用的评论原文，不能跨数据集 |
| GET /tasks/{id}/sources/{source_id} | 此任务的外部资料快照 |

创建时复用事件溯源的 `canonical_event()`，根据后端热榜快照核对热点 ID，使用服务端标题/URL/摘要/排名，不信任浏览器自行改写的事实。`feed_id` 始终保存实际榜单；只有可见二级榜单时 `board_id` 才非空，且必须匹配。导入数据再绑定 category/platform/feed/event，禁止切换后误用旧数据。

## 前端平台能力与联动

唯一后端能力表是 `app/public_opinion/settings.py::PLATFORMS`：EventLens ID → MediaCrawler ID。前端通过能力接口读取，不复制另一份七平台判断表。

- `frontend/src/components/event-lab/event-lab-panel.tsx`：复用 Workspace 传来的 selection、source、useBoard 数据；本地 `featureId` 为 public_opinion 时启用能力限制。
- `SpringDropdown` 的 option 支持 disabled/reason，鼠标选择有 guard；方向键、Home/End 只在可用选项中移动，Enter 也有禁用检查。
- 已选不支持的平台不会自动改变。平台框 `aria-invalid` 标红并显示指定提示，执行按钮禁用；切回事件溯源解除限制。
- 分区改变只保留新 categoryId；平台改变只保留 categoryId/platformId；榜单改变清除 trendId。原有“单榜单自动选择，多榜单显示下拉”不变。
- `context` 是当前有效热点；任务匹配同时检查分区、平台、feed、事件、功能，选择改变会 AbortController 取消旧任务。
- 导入组件是可选文件入口，没有新增自由文本事件名、链接或关键词必填框。格式见 `frontend/public/public-opinion-import.md`。

## 实际执行链（按文件和函数）

1. `frontend/src/components/layout/workspace.tsx::Workspace`管理热榜和实验室 `labSelection`，复用 `resolveEventLabSource` 和 `useBoard` 的配置/缓存。
2. `frontend/src/components/event-lab/event-lab-panel.tsx::EventLabPanel`：selection/source/data → 找到 `trend` → 构造 `context: EventLabEventContext`，不发送整榜。
3. 同文件 `submit()`：验证 context、feature、平台 → `run(feature, {event: context, featureId, datasetId})`。
4. `frontend/src/hooks/use-event-lab-task.ts::useEventLabTask.run()`：建立 AbortController、设置运行状态 → 调用功能 execute；旧请求取消后不能覆盖新状态。
5. `frontend/src/lib/event-lab-features.ts::eventLabFeatures` 的 public_opinion.execute → `requestPublicOpinion()`。
6. `frontend/src/lib/api/public-opinion.ts::requestPublicOpinion()`：复用 `eventPayload()` 组装上下文 → POST `/api/public-opinion/tasks` → 每秒 GET 状态 → 获取 report。重试时先查询旧任务，仍在运行则重新订阅，已失败才 resume。
7. `frontend/src/app/api/public-opinion/[...path]/route.ts::proxy()`：限定 API 命名空间 → 服务端请求 FastAPI；后端地址不会由浏览器输入决定。
8. `backend/app/public_opinion/api.py::create_task()`：Pydantic 参数 → supported/canonical 校验、会话或 dataset 绑定 → `OpinionStore.create_task()` 幂等入库 → `OpinionTasks.start()` → 立即返回 202。
9. `workflow.py::OpinionTasks.execute()`：任务 ID → 读不可变请求和阶段检查点 → `create_opinion_graph()` → `graph.ainvoke()`。
10. 图顺序：`post_discovery → comment_collection → comment_preparation → public_opinion_analysis → report_validation`。
11. `discovery.py::PostDiscovery.discover()` 创建 **PostDiscoveryAgent**（`create_deep_agent`）：动态事件数据作为 user JSON；模型自主调用 search_web、fetch_page、validate_posts、rank_posts。固定提示词在 prompts.py。只有实际搜索/阅读、平台 URL 可解析且已记录相关性理由的 ID 可以输出。
12. `search_web → app/event_trace/clients.py::TraceClients.search()`，真正调用 `POST https://api.deepseek.com/v1/tools/search`；fetch_page → `TraceClients.fetch()` → 公网 URL/DNS 校验 → `/v1/tools/fetch`。来源累积在 discovery.candidates/pages/verified；最终保存已验证帖子，不能让模型新增未见 URL。
13. `collector.py::MediaCrawlerAdapter.collect()`：逐个真实 Post → 独立子进程 `crawler_worker.py` → MediaCrawler 的 `main.main()`，使用已核实 detail CLI 参数 → upstream crawler → store callback → 最小化 JSONL。父进程逐行转换为 CommentInput，不重新按点赞数排名。
14. `preparation.py::prepare_comments()`：按来源顺序取前 N 条、去重/清洗、关联父评论和帖子 → store.save_dataset()。大评论正文留数据库，图 State 仅保存 dataset_id、帖子/统计/研究状态。
15. `research.py::OpinionResearch.investigate()` 创建独立 **PublicOpinionAgent**，首先实际读取 stats、少量评论和主题，再自主决定调用情绪/观点/立场/争议/时间/宏观工具。没有 Supervisor；两个 harness 的 task/execute/文件工具由 ToolPolicy 隐藏并拒绝执行，默认 StateBackend 不挂载宿主文件。
16. `analysis.py::CommentAnalysis.analyze()`：数据库评论 → 按字节预算分批 → `llm.py::structured()` 调现有 OpenAI-compatible LLM → Pydantic 分组归属 → 过滤不存在/重复引用 → 分批统一标签 → **Python 计算 count/percent**，写缓存。模型不能直接填写正式统计。
17. 语境工具：get_temporal_context 使用帖子/评论时间和 chinesecalendar 的对应年份法定节日，不拿今天解释旧事件；search_context/fetch_context 复用搜索/阅读服务；历史查询只查本地实际报告；现有溯源无历史 API 时 get_related_events 明确返回不可用。只有已读来源且逐字摘录可定位的宏观关联才保留，模型的“verified_fact”降为“有来源的推断”。
18. `workflow.py::validate_report()` 再次核对评论/来源/摘录、去除重复计数并重算比例 → `OpinionReport` → 数据库 → FastAPI report JSON。
19. React 的 `EventLabTaskWindow` 根据 mode=opinion → `PublicOpinionReport`，按 sections 类型渲染卡片/情绪条/宏观关联/评论。`CommentReference` 展开才读取原文；React 把外部内容当文本，不执行 HTML/组件代码。

## MediaCrawler 接口与排序核实

参考上游 main，检查日期 2026-11-19：
- [README](https://github.com/NanmiCoder/MediaCrawler)
- [许可证](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)：NON-COMMERCIAL LEARNING LICENSE 1.1，商业用途需取得权利人书面同意，不能用于规模化采集或扰乱平台。
- [真实命令参数](https://github.com/NanmiCoder/MediaCrawler/blob/main/cmd_arg/arg.py)

独立 checkout 安装其官方 README 中的依赖/Chromium，不将其依赖混装进 EventLens。设置：

```env
MEDIACRAWLER_HOME=/你的绝对路径/MediaCrawler
MEDIACRAWLER_PYTHON=/该项目虚拟环境/bin/python
MEDIACRAWLER_AUTHORIZED=false
```

仅在确认适用许可证及合法平台授权后设 true。平台会话变量在 `.env.example`，只读后端环境，不出现在命令参数、前端或日志。Cookie 失效/验证码/拒绝访问时不绕过；返回失败或部分成功，并支持导入。

Worker 实际调用参数：`--platform <code> --lt cookie --type detail --specified_id <id或url> --get_comment yes --get_sub_comment no --save_data_option jsonl`。通过上游 StoreFactory 挂接最小字段 sink，不改上游文件。部分平台不在分页层限制数量，sink 在第 N 条有效一级评论写完后停止，并做浏览器清理；最多可能多请求一页，不会先拉数万条再截断。评论计数按 ID 去重，source_rank 保留回调顺序（过滤后可以有间隔）。未知排名保留 null。

| EventLens / MC | 已核实源码接口 | 排序记录 |
| --- | --- | --- |
| xiaohongshu / xhs | `/api/sns/web/v2/comment/page`，cursor | unknown，未找到明确热门参数 |
| douyin / dy | `/aweme/v1/web/comment/list/`，cursor | unknown |
| kuaishou / ks | `request_rest_v2("/rest/v/photo/comment/list", ...)`，pcursor | unknown；当前热点目录无快手入口 |
| bilibili / bili | `/x/v2/reply/wbi/main`，DEFAULT=0 | 上游 field.py 注释为 popularity；运行时再检查枚举，记录 hot，不承诺等同网页排名 |
| weibo / wb | `/comments/hotflow`，max_id/max_id_type | unknown；接口名不单独证明前端热门排序 |
| tieba / tieba | 浏览器读取帖子页面和楼层分页 | unknown，保留提取顺序，不称热度榜 |

在线 MVP 采集一级评论；**二级回复目前通过导入路径支持，在线补充采集未启用**。不同版本、平台接口、会话状态仍需实采验证；能力接口的 collector_ready 是配置就绪，不是实时成功保证。

## 清洗、预算与缓存

清洗包括 HTML 转义/标签处理（不执行脚本）、Unicode NFC、控制字符和换行规范化、空内容过滤、按 platform/post/comment ID 去重。相同文字的不同 ID 保留并标记 duplicate_text。评论原文与清洗文本均保存。采集时间戳转 ISO；无时区的上游中文平台时间按 Asia/Shanghai 转换，导入时间必须带时区，未知日期留空。

默认每帖前 50 条、最多 20 帖/1000 条一级评论，回复最多 100（不进入一级统计）。每批最多 35 条且按 10000 UTF-8 字节预算进一步缩小，单评论默认最多 1200 字进入模型；完整原文仍可查看。工具按需读取最多 25 条/12000 字节。没有向量库、Embedding 或额外情感分类模型。

模型调用最多 60 次，任务 Token 准入预算 120000（输入 UTF-8 字节加输出上限的保守估算，和上游实际 usage 分开记录）；所有 batch 与两个 harness 共用同一个 Budget。预算是在 HTTP 调用前检查，持久化用量；上游没有 usage 时不编造精确消耗。每次输出最多 2500 token、模型并发 1；单分析工具 180 秒，全任务 600 秒。发现 90 秒、搜索最多 5 次、阅读最多 15 次；语境独立最多 3 次搜索、5 次阅读。底层 Search/Fetch 沿用最多一次瞬时错误重试，因此最多 HTTP 尝试数可为逻辑调用数的两倍。工具调用合计最多 100，Agent 循环也有限制。

完整变量见 `.env.example`。批次缓存键包含提供方地址、模型、Prompt 版本、任务类型和实际批次内容；同一工具再次执行优先缓存。跨批次只归并标签、不让模型重算评论数量；事件日期、文章发布日期、采集日期、评论日期分别保留。长评论、覆盖不全、来源集中、排序未知和导入来源未独立核实均向用户说明。

## 验证与边界

自动化测试命令（不消耗真实 API）：

```sh
cd backend
.venv/bin/python -m unittest discover -s tests -v
cd ../frontend
npm run typecheck
npm run build
```

`tests/test_public_opinion.py` 使用测试评论和可调用工具的 ScriptedModel，运行真实 Deep Agents 与 LangGraph，不把预生成报告接进正式模式。`tests/serve_opinion_fixture.py` 是单独的 TEST ONLY 浏览器验收服务器，app.main 从不导入它，数据只存在临时目录。它不能用于验证真实采集或模型研究质量。

本次实际联网检查：现有模型成功完成 Deep Agents 结构化工具输出；官方 Search 请求超时；Fetch 被本地公网 DNS 安全检查拦截，公开站点在此环境被解析为 198.18.* 测试地址。没有放宽 SSRF 规则。MediaCrawler 未提供合法会话及授权配置，**七平台端到端在线采集尚未验证**。导入、图编排、报告、引用等在测试数据下通过；用户导入真实授权评论后可进行真实 LLM 分析，不能把测试报告当真实舆情。

PostgreSQL 17 已在隔离临时 schema 中实际验证数据集、评论顺序、缓存、检查点和报告写读；结束只清理本次测试 schema。自动化回归仍使用临时 SQLite，方便无 Docker 环境运行。

当前不包含：用户鉴权、分布式队列、多 worker 恢复、模型调用位置精确续跑、全平台用户代表性采样、平台排序独立逆向验证、在线二级回复采集。节日日历是法定假期数据，不覆盖所有地方习俗/节气；其他关联须通过真实外部来源核实，资料不足可以不输出宏观模块。

## 文件清单与职责

新增文件均在现有业务目录中：

| 文件 | 职责 |
| --- | --- |
| app/public_opinion/__init__.py | 独立业务包 |
| app/public_opinion/settings.py | 单一平台能力映射、环境变量、采集配置检查 |
| app/public_opinion/schemas.py | 请求、帖子、评论、分析模块、来源和最终报告的 Pydantic 类型 |
| app/public_opinion/api.py | 能力、导入、创建、查询、取消、恢复、报告和引用接口 |
| app/public_opinion/store.py | SQLAlchemy 表、任务、顺序评论、缓存、外部资料和报告读写 |
| app/public_opinion/preparation.py | JSON/CSV 校验、清洗、按序去重截取、数据统计 |
| app/public_opinion/collector.py | 七平台 URL/ID 识别、受控子进程及评论字段转换 |
| app/public_opinion/crawler_worker.py | 独立环境启动真实 MediaCrawler detail 模式、最小化顺序回调输出 |
| app/public_opinion/llm.py | 复用模型配置、硬预算、实际 usage、工具权限策略 |
| app/public_opinion/prompts.py | 帖子发现、舆情研究、批次分析的独立提示词 |
| app/public_opinion/discovery.py | PostDiscoveryAgent 与搜索/读取/验证/排序工具 |
| app/public_opinion/analysis.py | 有界批次、标签归并、实际处理样本、程序计数和缓存 |
| app/public_opinion/research.py | PublicOpinionAgent、自主分析工具、日历和有来源的宏观研究 |
| app/public_opinion/workflow.py | 外层 LangGraph、后台任务、检查点、取消与最终校验 |
| tests/test_public_opinion.py | 无付费 API 的确定性测试，真实 harness 与图运行 |
| tests/serve_opinion_fixture.py | 明确标记 TEST ONLY 的独立浏览器验收后端 |
| frontend/src/types/public-opinion.ts | React 使用的报告与进度协议 |
| frontend/src/lib/api/public-opinion.ts | 文件导入、后台任务创建/轮询/取消/恢复 |
| frontend/src/app/api/public-opinion/[...path]/route.ts | Next.js 服务端代理 |
| frontend/src/components/event-lab/opinion-import.tsx | 选择现有热点后的可选授权评论导入 |
| frontend/src/components/event-lab/public-opinion-report.tsx | 动态报告、统计、模块和原文按需查询 |
| frontend/src/components/event-lab/public-opinion-report.module.css | 与现有主题一致的报告/导入样式 |
| frontend/public/public-opinion-import.md | 用户可直接打开的导入字段说明 |
| backend/PUBLIC_OPINION.md | 本文：配置、调用链、验证与限制 |

修改文件：app/main.py 注册新路由与生命周期；requirements.txt 增加 Deep Agents/模型适配/数据库/日历依赖；compose.yaml 加可选 PostgreSQL；.env.example 加不含密钥的配置；.gitignore 忽略数据文件；README.md 加入口。前端只扩展 event-lab-panel、event-lab-task-window、use-event-lab-task、event-lab-features、SpringDropdown 及其样式；event-trace API Client 仅提取共用的 eventPayload，不改事件溯源业务。Workspace、热榜 catalog/useBoard、Navigation、ChatPanel 和 Composer 未改。

报告的 prepared_count 是整理后可分析数量；导入时 analyzed_count 为 0。报告分析数由实际完成批次的评论 ID 集合计算，未完成记录不进入百分比分母；预算不足保留部分结果并标 partial。导入来源 origin=imported，输入数 input_count 与真实在线采集数 collected_count 分开，界面不会把导入称为在线采集。

在线任务在开始付费帖子搜索前，还会通过独立解释器检查 MediaCrawler 依赖、真实 detail 参数和 Chromium 可执行文件；检查失败立即返回明确 503。此检查不登录或访问平台，不能代替实际会话可用性核验。B站源码还会在首批回复前加入置顶评论，报告会注明 source_rank 是含置顶的回调顺序。

本次验收记录：后端 48 项测试通过（原有 24 项回归 + 新增 24 项），TypeScript 和 Next.js 生产构建通过。浏览器检查了平台禁用/键盘跳过、已选不支持平台的标红拦截、切回事件溯源、无热点校验、单/多榜单、配置缺失提示、TEST 文件导入、执行到报告、引用展开、切换平台清空旧结果。390px 视口在既有导航过渡结束后 document.scrollWidth=390，无横向溢出。TEST 报告不代表真实舆情。

另做了两项真实模型冒烟检查：Deep Agents 的结构化工具调用成功；用自建 TEST 文本调用真实模型的 BatchOutput JSON Schema 解析也成功（未保存生产报告）。这验证模型协议兼容性，不等于真实公众评论调查已完成。

宏观外部检索失败不会丢弃已完成的评论研究；报告保留有依据的模块并标出局限。语境工具另有 60 秒时间窗口和 40000 Token 保守准入预算，仍受全任务总预算约束。

MediaCrawler 子进程只继承必要系统/网络环境及当前平台 Cookie，不继承 EventLens 模型密钥、搜索密钥、其他平台 Cookie 或数据库连接串。

## 本机 MediaCrawler 安装记录（2026-11-19）

- 官方仓库： https://github.com/NanmiCoder/MediaCrawler
- 安装位置：`/Users/jiangyiming/Downloads/Apps/work/MediaCrawler`，与 EventLens 并列，未复制到前端或后端依赖中。
- 已验证提交：`09ed1ec62d885dab422a53de999f52ac0bd4966b`。上游源码与锁文件保持未修改。
- 使用仓库固定的 Python 3.11，已创建独立 `.venv`（Python 3.11.18），依据 uv.lock 安装 89 个依赖。安装时使用临时 uv 工具；日常运行可以直接使用下面的 Python 路径。
- Playwright 1.61.0，Chromium 149.0.7827.55，标准无头模式实际启动/关闭成功。
- `backend/.env` 仅补充或更新 `MEDIACRAWLER_HOME` 和 `MEDIACRAWLER_PYTHON`，已有 API Key 未改；未启用采集授权、未填写 Cookie。
- 验证通过：`main.py --help`、Node.js/ExecJS、EventLens `MediaCrawlerAdapter.preflight()`；上游 StoreFactory、B站评论顺序、抖音/快手 URL 与贴吧 detail 参数测试共 30 项通过。
- 本次未登录任何平台、未执行真实采集，因此安装完成不代表平台会话或采集授权已配置。

日常查看命令：

```sh
cd /Users/jiangyiming/Downloads/Apps/work/MediaCrawler
.venv/bin/python main.py --help
```

配置文件中的实际路径：

```env
MEDIACRAWLER_HOME=/Users/jiangyiming/Downloads/Apps/work/MediaCrawler
MEDIACRAWLER_PYTHON=/Users/jiangyiming/Downloads/Apps/work/MediaCrawler/.venv/bin/python
```

## 微博登录配置工具

新增 `backend/scripts/mediacrawler_login.py`，仅处理本人互动登录，不调用 MediaCrawler 搜索或 detail 采集。使用官方登录模块显示二维码，登录后再通过微博移动端 `/api/config` 检查真实登录状态。只有验证成功，才把 `.weibo.cn` / `m.weibo.cn` 范围的会话写入本机 `backend/.env`，不会打印 Cookie；配置文件权限设置为 0600。其他 API Key 保留。

仅在已确认个人非商业学习研究用途及数据访问权限时使用：

```sh
/Users/jiangyiming/Downloads/Apps/work/MediaCrawler/.venv/bin/python \
  /Users/jiangyiming/Downloads/Apps/work/EventLens/backend/scripts/mediacrawler_login.py \
  --platform weibo --confirm-authorized
```

用户本人在独立 Chrome for Testing 窗口扫码、完成平台要求的验证。超时或登录验证失败时，不保存未确认的会话。工具不读取日常 Chrome 个人资料、不开启远程调试，也不自动采集。保存成功后重启 FastAPI，再执行已选择热点的任务。验证码由账号本人完成，工具不处理验证码。

微博会话配置记录：用户已确认个人非商业学习研究用途与相应访问权限，并本人完成扫码。官方移动端登录状态校验与实际 MediaCrawler `create_weibo_client(...).pong()` Cookie 模式校验均成功；未执行帖子或评论采集。后台已重新加载授权和会话。其他平台未配置登录。会话可能过期，届时需重新本人登录；本记录不包含任何凭据。

## 帖子发现预算与 Fake-IP 修复

预算在发出模型调用前，仍用输入字节和输出上限做保守准入；成功且上游返回完整 usage 后，按实际 Token 结算并释放未使用预留。失败、取消、缺少 usage 的调用继续按完整预留计费控制，恢复也保留预算。此前把每次成功调用的预留永久累加，可能在实际用量尚低时提前停止；已修复。

`discovery_diagnostics` 保存实际检索次数、原始搜索结果数、候选/已读/已验证/已排序帖子数与最近的安全错误；模型预算不足和阶段超时分别报错。

当前机器的 DNS 代理将公网域名映射到 198.18/15。可选 `PUBLIC_OPINION_PUBLIC_DNS_FALLBACK=true` 仅对这一专用 Fake-IP 范围进行固定 Cloudflare HTTPS DNS 的 A/AAAA 独立核验。必须所有返回地址都是公网地址才允许调用远端 Fetch，私网/环回/未知解析/核验失败仍拒绝；不修改系统 DNS、不向 DNS 服务传递 API Key、不绕过目标网站的登录或访问限制。仅用于公众舆情 Fetch，原事件溯源的解析逻辑保持不变。

## 微博一级评论与浏览器启动修复

实际 hotflow 响应中，一级评论的 `rootid` 可能等于自身 `id`。原适配器将这些记录误当回复全部过滤。现在仅对微博规范化这一自引用；真实回复仍保留父级，不提升为一级评论，也不改变其他平台规则。

微博采集复用上游 `WeiboLogin` Cookie 模式、`WeiboCrawler.create_weibo_client()`、登录 `pong()`、`get_note_all_comments()` 分页和官方 store 回调，使用独立环境已安装的 Chromium。帖子已经过发现阶段读取验证，不再为评论采集额外打开桌面首页。仍按接口顺序限量截取，排序模式保守记录为 unknown；未声称为平台前端热门排名。

付费帖子发现前的 preflight 现在实际启动并关闭 Chromium，提前发现可执行文件存在但运行权限不足的情况。后端须在允许启动浏览器的本机终端运行；沙箱禁止进程启动时不能仅以文件存在判定运行环境可用。

2026-11-19 真实验证：同一用户选择事件的官方 Search 返回可解析帖子，Fetch 成功读取，2 次检索后验证 5 个帖子；修复后的完整 MediaCrawlerAdapter 对首帖采集 3 条真实一级评论、顺序 1–3、无采集警告。此记录证明发现和首帖采集，不等于所有平台或完整分析报告验证通过。自动化测试 64 项通过，测试不消耗真实 API 额度。

随后恢复同一任务，真实完成 11 条一级评论的主题、情绪、观点与代表评论模块，并保存报告。状态为 partial：其中一帖采集未完整结束，后续模型调用触及预算准入上限，保留已完成模块；未生成缺少核验的宏观关联。不是全平台或完整覆盖，其他六个平台在线会话未验证。未提高预算上限或使用模拟评论填充。

## 舆情报告可视化（2026-11-19）

本次只扩展报告、确定性统计和证据读取，不改变导航、选择器、热点聚合、事件溯源或聊天布局。新增前端依赖 Recharts 3（单一图表库），无需新增数据库表、环境变量或模型服务。

数据流：

1. `analysis.py::CommentAnalysis.analyze()` 输出真实评论归属 `Section.analyzed_sample / data[].evidence`，保留明确立场议题 `issue`。新版本主题允许同一评论多重归属，情绪/立场仍为单一归属；Prompt/cache 版本同步更新。
2. `workflow.py::validate_report()` 核对评论 ID、分母和来源，允许主题跨组重叠，拒绝情绪重复计数；调用 `visualization.py::enrich_report()`。
3. `enrich_report()` 完全从数据库的有效一级评论和已保存归属重算图表，忽略模型填写的 count/percent。`OpinionReport.charts` 包含图表 ID、类型、样本量、说明、数据点、精确的评论引用；`context_timeline` 保留资料发布时间与未知关联时间。
4. `GET /api/public-opinion/tasks/{id}/report` 对旧报告同样做只读投影，不迁移数据、不重跑 Agent。`GET .../{id}/chart-comments?chart_id=...&point_id=...&offset=0&limit=10` 只返回该点实际计数的评论，分页上限 30，保留数据库采集顺序。
5. 前端 `public-opinion-report.tsx` 按真实存在的模块分层排版；`opinion-charts/visualization-registry.tsx` 将图表 type 映射到懒加载 React 组件；`chart-plots.tsx` 使用 Recharts 绘制环形、横向柱状与时间折线图。`comment-drilldown.tsx` 处理筛选、分页、加载、重试和请求取消。
6. `contextual-timeline.tsx` 展示有证据的背景节点；点击展开解释、事实/推断/假设等级、原文摘录和原始资料链接。抓取时间、资料发布时间、事件时间明确区分。

展示条件：

- 情绪：仅使用已完成分析批次作为分母，漏分类/非法情绪标签归入“无法判断”；不隐藏这部分样本。
- 主题：按评论数量降序，可重叠，明确说明占比不相加为 100%；不是饼图。点击条形或键盘数据列表按钮查看真实评论。
- 立场：必须保存明确 issue、实际完成批次且存在有效归属。旧报告未保存 issue 时不强行推断或绘图；一个议题下采用横向分组柱状数量对比。
- 时间：至少 6 条带时区的有效时间，覆盖率至少 80%，至少 3 个真实聚合时段。跨度小于 6 小时按 15 分钟，至 2 天按小时，至 60 天按日，其余按周；统一 Asia/Shanghai。仅绘制有记录的时间段，横轴保持真实时间间距，不补零、不平滑补点，标题为“已采集样本的评论发布时间分布”。缺失时间不计入这张图的分母并注明有效数量。
- 帖子贡献：按数据库中实际保留的一级评论计数，二级回复不混入，可显示零贡献帖子。含未完成语义分析的保留评论，明确不是帖子总评论量。
- 雷达：后续增量已定义可核验的样本文本指标，条件、归一化、柱状降级和最新文件清单见 frontend/docs/public-opinion-visualization.md。小样本或没有可靠指标时仍不显示，不输出模型自由评分。
- 图表失败仍有可操作的数据列表；评论加载失败可重试。图例/数据按钮支持键盘，Recharts accessibility layer 开启。配色由共享 palette 和 CSS 变量统一，继承现有表面/文字主题；`data-theme="light"` 提供深色语义色板。图表关闭补间动画，尊重减少动态偏好；不新增全局主题切换器。

验证命令：

```sh
cd backend
./.venv/bin/python -m unittest discover -s tests -q
cd ../frontend
npm ci
npm run typecheck
npm run build
```

独立浏览器验收脚本：`frontend/tests/opinion_visualizations_browser.py`。使用含 Playwright/Chromium 的独立 Python 环境，参数指定正在运行的前端地址和**已经保存的真实任务 ID**：

```sh
/Users/jiangyiming/Downloads/Apps/work/MediaCrawler/.venv/bin/python \
  frontend/tests/opinion_visualizations_browser.py \
  --base http://127.0.0.1:3101 --task <已完成任务ID>
```

浏览器测试只回放保存事件的榜单快照与任务创建响应，报告、统计和评论读取走真实本机 API；不会新建 Agent 或消耗额度。单元测试的合成场景仅位于 tests，不进入正式报告。报告可能为 partial，图表仅展示有证据的数据；本升级不会补足未完成研究。

本次可视化增量文件清单（相对项目根目录）：

| 文件 | 变更 | 职责 |
| --- | --- | --- |
| backend/app/public_opinion/visualization.py | 新增 | 根据保存归属、一级评论和时间生成可信图表 JSON、背景节点 |
| backend/app/public_opinion/schemas.py | 修改 | ChartPoint、OpinionChart、ContextNode、报告可视化字段与立场 issue |
| backend/app/public_opinion/analysis.py | 修改 | 主题多重归属、记录立场议题、分析缓存版本升级 |
| backend/app/public_opinion/prompts.py | 修改 | 主题可多选，情绪/立场保持单分类 |
| backend/app/public_opinion/workflow.py | 修改 | 归属校验与图表生成集成 |
| backend/app/public_opinion/api.py | 修改 | 旧报告实时统计投影、严格匹配图表数据点的分页评论接口 |
| backend/tests/test_opinion_visualization.py | 新增 | 统计、时间、重叠、缺失、旧报告和分页接口测试 |
| frontend/src/types/public-opinion.ts | 修改 | 可扩展图表、节点、分页数据类型 |
| frontend/src/components/event-lab/public-opinion-report.tsx | 修改 | 报告概况、图表、观点、分布、关联、局限的动态布局 |
| frontend/src/components/event-lab/public-opinion-report.module.css | 修改 | 报告标题样式 |
| frontend/src/components/event-lab/opinion-charts/chart-plots.tsx | 新增 | 情绪、主题、立场、时间、贡献 Recharts 组件 |
| frontend/src/components/event-lab/opinion-charts/visualization-registry.tsx | 新增 | 类型注册、懒加载、数据列表、图表错误降级 |
| frontend/src/components/event-lab/opinion-charts/comment-drilldown.tsx | 新增 | 原始评论分页、读取失败重试、切换取消旧请求 |
| frontend/src/components/event-lab/opinion-charts/contextual-timeline.tsx | 新增 | 背景节点交互和来源证据展开 |
| frontend/src/components/event-lab/opinion-charts/palette.ts | 新增 | 统一语义颜色映射 |
| frontend/src/components/event-lab/opinion-charts/opinion-charts.module.css | 新增 | 现有主题适配、窄屏、Tooltip、图例和证据样式 |
| frontend/tests/opinion_visualizations_browser.py | 新增 | 保存真实报告的无额外付费浏览器验收脚本 |
| frontend/package.json、frontend/package-lock.json | 修改 | 添加并锁定 Recharts 3 |
| backend/PUBLIC_OPINION.md | 修改 | 本文说明、文件清单、数据流和验证规则 |

验证记录：后端 75 项测试通过（本次新增 11 项），TypeScript 检查与 Next.js 生产构建通过。已保存真实报告经实际前端代理返回主题、情绪、时间、贡献四类图表，共 11 条有效一级评论；本次没有重新调用模型。这份真实报告情绪为“无法判断”11 条，因此显示灰色整环，不会为了演示色彩而改写分类。立场图和宏观节点在单元数据中验证条件，不声称当前报告具备这些研究结论；雷达没有符合条件的量化数据。

## 平台登录引导与真实会话状态（2026-11-19）

前端在公众舆情分析选择平台后读取登录状态。配置 Cookie 不等于登录有效；配置存在但未验证时，自动执行一次无界面校验，不会打开登录窗口，不会搜索帖子、采集或调用模型。未登录、验证中、失效、验证失败和运行环境缺失在实验选择栏内提前提示；未通过验证时禁止在线采集执行。事件溯源和已绑定的授权评论导入不受会话状态限制。

用户点击“登录平台”后，后端启动独立本机 Chromium，打开该平台官方登录页面；用户本人扫码/输入账号及完成平台要求的验证。登录后点击“完成登录并验证”。只有验证通过且取得 Cookie 才保存会话；取消、超时或无法确认时不覆盖已有会话。保存采用私有临时文件和原子替换，保留其他 .env 配置、权限 0600，并立即更新当前后端进程，无需重启。前端不接收密码、二维码 token 或 Cookie。

接口（均在 `/api/public-opinion` 下）：

| 方法/路径 | 作用 |
| --- | --- |
| GET /sessions/{platform} | 本平台状态与短期验证缓存，不发起外部请求 |
| POST /sessions/{platform}/check | 后台无界面验证，立即返回 checking |
| POST /sessions/{platform}/login | 明确点击后启动本机登录窗口，立即返回 logging_in |
| POST /sessions/{platform}/confirm | 用户完成登录后请求验证 |
| DELETE /sessions/{platform} | 取消本平台操作并关闭子进程 |

状态：not_logged_in、unverified、checking、logging_in、verified、expired、unavailable、error、cancelled。只有服务器明确返回未登录才标记 expired；网络/浏览器错误不当作过期。验证有效期 5 分钟，Cookie 变化立即失效；前端定期读取缓存，过期后重验。任务创建与尚未完成采集的任务恢复，后端均再次检查当前验证状态。已保存/导入的数据集不需要平台在线会话。

真实能力范围：

- 微博：官方移动端 `/api/config` 的 login 布尔状态；已用本机已有授权会话实际验证通过。
- 哔哩哔哩：官方 `/x/web-interface/nav` 的 isLogin 状态；调用逻辑已实现，尚无该平台账号完成本机真实登录验收。
- 小红书：复用当前 MediaCrawler `create_xhs_client().query_self()` 与 selfinfo success；快手复用当前 GraphQL pong。均已接入交互与验证逻辑，仍需用户本人登录后确认当前环境可用性。
- 抖音、贴吧：当前上游 pong 仅依赖 Cookie/localStorage 标记，无法可靠证明服务器会话仍有效。本版明确说明限制，不开放会制造“已验证”假象的在线登录入口，仍支持授权评论导入。后续须补充并实测可靠的远端验证器再开放；这不是声明平台本身无法登录。
- 不为当前热榜目录中不存在的快手新增数据源。

运行约束：这是本机开发版登录协调器，仅本机 GUI 环境可用，不是远程多用户账号系统。不挂载个人日常浏览器资料，不绕过验证码、访问限制或平台验证。一次只允许一个交互式登录、最多两个会话操作；重复点击复用同一 job，校验最长 45 秒、登录最长 330 秒，服务关闭会取消并关闭子进程。动作接口检查本机来源与自定义头，Next.js 代理拒绝跨站动作；不允许外部网页触发本机浏览器。

本次文件：

- `backend/app/public_opinion/session_protocol.py`：两个 Python 环境共享的纯标准库平台映射、官方域名和 Cookie 字段过滤。
- `session_worker.py`：由 MediaCrawler 独立 Python 执行的浏览器登录/校验，不运行采集器。
- `sessions.py`：平台隔离的状态、预算、取消、缓存、私有凭据保存与执行校验。
- `session_api.py`：以上 HTTP 接口。
- `backend/app/main.py`：协调器生命周期；`api.py`：创建/恢复任务校验及能力区分。
- `frontend/src/hooks/use-platform-session.ts`：平台状态读取、后台检查、轮询、取消过期请求，防止跨平台状态串用。
- `frontend/src/components/event-lab/platform-session-notice.tsx` 与同名 CSS：登录提示、登录/完成验证/取消/重新检查按钮。
- `event-lab-panel.tsx`：沿用选择器和执行按钮，集成在线会话拦截，保留授权导入和事件溯源路径。
- `frontend/src/types/public-opinion.ts`、`frontend/src/app/api/public-opinion/[...path]/route.ts`：协议与本机安全代理。
- `backend/tests/test_platform_sessions.py`：状态、保存、验证、平台隔离、取消、预算及 API 安全测试；现有测试仅补充 session fixture。
- `frontend/tests/platform_sessions_browser.py`：显式 TEST 响应的浏览器交互测试，不登录实际账号、不创建 Agent 任务。

无需新增依赖、环境变量或数据库表。继续使用已有 MEDIACRAWLER_HOME、MEDIACRAWLER_PYTHON、MEDIACRAWLER_AUTHORIZED 及各平台 Cookie 配置。登录验证状态仅短期内存缓存，后端重启后需重新校验；已有 Cookie 仍保存在本机 backend/.env。

本次验证：89 项后端测试通过（新增会话相关 14 项），TypeScript 与生产构建通过。真实前端代理检查小红书返回 not_logged_in、提供登录能力；使用已有授权微博会话执行无界面验证返回 verified / collector_ready=true；跨站登录请求被真实 Next.js 代理返回 403。浏览器以显式 TEST 会话响应验证平台切换、手动登录/取消/完成校验、错误重试、导入绕过登录、事件溯源不受影响及移动端，无真实登录弹窗或 Agent 费用。小红书等其他账号的完整扫码与采集仍需用户本人在界面操作，未声称实测通过。

## 小红书公开 Fetch 失败与短帖修复

实际失败任务：5 次公开搜索均返回空结果；原始小红书链接由 DeepSeek Fetch 返回 HTTP 404。该服务没有本机用户会话，不能将其 404 解释成“本机登录过期”。使用已授权的本机 MediaCrawler 客户端读取同一原始链接，返回匹配 ID、12 字符标题、52 字符正文及真实发布时间；原来统一要求至少 80 字符，也会误排除此类短帖。

新增 `post_reader.py / post_read_worker.py / xhs_context.py`：仅对真实候选小红书 URL，在公开 Fetch 未成功时通过本机已配置授权会话读取。使用当前上游 `create_xhs_client().get_note_by_id(note_id, xsec_source, xsec_token)`，保留来源 URL 的令牌，不生成替代令牌；只接收匹配帖子 ID 的非空 desc。返回最小文字与发布时间，不保存作者资料，不向第三方 Fetch 发送 Cookie，不下载图片/视频。每次最多 30 秒、每任务最多 3 个授权读取候选，仍受发现阶段总预算约束。平台拒绝访问、验证要求、帖子不存在时停下，不切换身份或绕过限制；公共读取的安全 URL/DNS 拦截、403/429 等拒绝也不通过此通道绕过。

`discovery.py` 区分 public_fetch / authorized_platform，只有有实际文字且相关性经 Agent 记录的帖子才能进入采集；短文字并不等于空正文，只有标题的对象仍拒绝。提示词优先读取用户选中原始链接，读到相关帖子即可结束，不为凑数量继续空搜索。新增诊断：公开读取失败数、授权读取尝试数与成功数；失败信息包括实际计数与 HTTP 状态。

`crawler_worker.py` 的小红书分支复用同一授权客户端直接调用上游 `get_note_all_comments`，不再额外执行桌面首页/detail/媒体下载流程；仍通过上游 store 回调保留顺序和每帖数量上限。实际数据访问条件不满足时仍报错，不用摘要或 Mock 评论补缺口。

`Post.read_method` 保存阅读来源，报告局限性注明本机授权阅读与未核验视听内容。原事件溯源的 TraceClients 和其他平台的公开阅读不变。本次新增 9 项无付费测试，后端共 98 项通过；独立适配器已真实读到同一帖的 52 字符正文。完整任务验证结果另行记录，单次阅读成功不等于报告成功。

同一失败任务恢复后的真实验证：小红书会话复核成功，原始帖子经授权阅读取得匹配 ID 与短文字，Agent 验证并记录相关性，MediaCrawler 原始顺序采集 50 条一级评论，实际完成 50 条主题分析与代表评论模块，保存 partial 报告；前端代理 GET report 返回 200，并生成主题、帖子贡献和真实时间分布图。部分完成原因包括原帖文字主要是标签、视听内容未核验、公开搜索覆盖不足及后续研究触及模型预算。没有提高预算、补造情绪分类、替换事件或使用 Mock 评论。此记录不代表所有小红书帖子都能读取。


最新可视化增量已补齐立场堆叠图、完整时间序列、固定定义的样本特征雷达/柱状切换与部分完成说明。详细数据链路、文件清单及104项测试结果见 `frontend/docs/public-opinion-visualization.md`。这替代了早期“尚无雷达定义”的实现状态，不改变历史报告的研究结论。

## 总体评价与证据浏览升级（2026-11-19）

报告现在以唯一 `overall_assessment` 字段保存研究后综合判断（summary、core_judgment、key_findings、section_types、evidence、source_ids、status、reason）。旧 insight 只作输入兼容，不重复输出。`research.py::OpinionResearch.investigate` 在实际工具分析和资料核验结束后调用 `assessment.py::synthesize_assessment`，使用同一模型和剩余任务预算；研究阶段在原有总预算内预留最终综合空间，不增加限额、不虚增消费。提示词独立位于 `prompts.py::ASSESSMENT`，模型仅接收有界的真实模块、评论引用、图表统计和局限信息，输出经 Schema、引用、统计叙述校验后保存。图表解读保存在 chart_interpretations。失败时保留真实研究模块，明确总评未完成。

GET report 不调用模型、不自动补写历史内容。旧报告的实际 insight 显示为历史研究摘要；通用模板占位不会冒充综合结论。新增 GET `/api/public-opinion/tasks/{id}/evidence`，按 section_index/group_index、assessment=true 或 chart_id 返回严格属于已保存报告的分页证据预览；图表点接口支持 preview=true，删除 raw_content 并截断为 240 字符；单条完整内容仍使用已有 `/comments?post_id=...&comment_id=...`。前端默认折叠，每页 3 条，两行预览、点开才读取全文。

最新 115 项后端测试通过，前端类型检查和生产构建通过。真实保存报告基于原研究生成 330 字总评与 4 段图表解读，未重新搜索或采集，继续保留 partial 状态。真实和独立 TEST 报告均完成浏览器布局及证据联动验收。完整文件表、调用链和命令见 `frontend/docs/public-opinion-visualization.md` 的“总体评价优先与紧凑证据浏览”。未新增依赖、环境变量或数据库表。

### 大上下文预算不足时的精简分析

模型调用数和 Token 准入预算是两种限制。Token 准入包含已结算消费、未结算保留量、下一请求 UTF-8 保守估算，以及最终报告预留空间；因此实际消费尚未达到上限时，下一条大请求也可能无法进入。`llm.py::Budget.reserve` 现在分别说明次数或 Token 限制，Token 提示列出累计计入、上限、最终预留、下一请求估算和当前可用量；被拒绝的请求不发送、不计费，也不增加调用计数。

`research.py::OpinionResearch.investigate` 遇到此限制、且尚无有效基础主题时，使用相同的数据范围/有限评论读取/主题工具做精简分批分析，绕开累积的 Harness 历史与工具定义。它仍使用原预算和原有总评预留，不增加限额、不清零消费、不补造分析。如果紧凑批次也无法进入，则保留明确错误；有真实分析时生成 partial 报告，未完成的维度不伪称完成。数据集和已完成批次缓存可复用，恢复不重新搜索/采集。新增两个回归场景（大 Harness 不适配但小批次可成功、连小批次也不足时必须停止），共 117 项测试通过。

实际失败任务在消费 67,489 Token 后从已保存的数据阶段恢复，未重新搜索/采集，44 条评论主题分析完成，生成 275 字总体评价并保存 partial 报告；最终累计 17 次模型调用、86,603 Token，未提高默认 120,000 限额。前端代理和浏览器真实报告验收通过（主题、时间、贡献、特征图、两行预览、分页、全文、失败重试、手机及主题适配），浏览器未新建 Agent 任务。页面原来仍停留在错误状态时，点原任务的“重试”会先查询状态，发现已完成后直接读取保存报告，不再研究。

### Fake-IP 独立 DNS 服务故障切换（2026-11-20）

小红书失败任务在帖子发现阶段被 URL 公网校验拦截，尚未进入评论采集。本机代理返回 `198.18.*` Fake-IP；原来固定 Cloudflare DNS 服务在当前网络连接失败，而 Google 与 AliDNS 的 A/AAAA 查询实测可用。`network.py::PublicDNSResolver` 改为按 Cloudflare、Google、AliDNS 的固定 HTTPS 地址依次核验，保留原来的显式 PUBLIC_OPINION_PUBLIC_DNS_FALLBACK 开关。每次查询 2.5 秒、全流程最多 8 秒、成功缓存 60 秒；仅网络/服务不可用时切换，任意已返回的私有/异常地址都立即拒绝，不通过其他服务覆盖。A 和 AAAA 都检查，不放行私网、不跳过安全校验，不将 Cookie 或 API Key 发送给 DNS 服务。

修改：network.py、tests/test_opinion_budget_network.py、.env.example 和本文。120 项后端测试通过，涵盖备用服务接管、私有地址遇另一查询超时仍须拒绝、全部服务失败不放行、Fake-IP 开关及缓存。修复后的真实小红书域名公网核验通过；DNS 通过不等于该帖子正文、登录会话或评论采集已经验证成功。

同一失败任务的原始链接进一步验证：公网校验通过；第三方 DeepSeek Fetch 仍返回 HTTP 404，随后现有本机授权阅读器取得身份匹配的 57 字符真实正文。此验证没有运行搜索、LLM、评论采集或完整 Agent 任务，不代表评论与最终报告已验收。后端已重启加载修复，用户可从原失败任务“重试”。
