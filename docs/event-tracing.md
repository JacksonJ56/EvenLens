# 事件溯源：配置与实际调用链

[返回项目首页](../README.md)


在 `backend/.env` 填写 `DEEPSEEK_API_KEY`。模型独立配置 `EVENT_TRACE_LLM_API_KEY`、`EVENT_TRACE_LLM_MODEL` 和 `EVENT_TRACE_LLM_BASE_URL`，地址填 OpenAI 兼容的 API 根路径，例如 DeepSeek 的 `https://api.deepseek.com/v1`，不要加 `/chat/completions`。所选模型需支持 JSON Object 模式。同一账户可以在两个变量分别配置凭据。所有凭据仅在服务端使用；Copilot 也可在 Next.js 服务端复用模型配置。改完重启后端。需要新增依赖时，在 `backend/` 运行 `python -m pip install -r requirements.txt`。

打开「事件实验室」，沿用已有的热点分区、平台、榜单和热点选择。单榜平台直接选热点，例如「综合 → 微博」。多榜平台先选榜单，例如「科技 → IT之家 → IT资讯最新」。在实验功能下拉选择「事件溯源」，点击「执行」。展开时间线节点可以看到详情、引文及原文入口。搜读受上游权限、站点访问策略和当前资料质量影响，结果可能标为「部分结果」，并列出资料缺口或补充搜索词。公众舆情分析是已接入的第二个实验功能，实验功能三仍为演示占位；实验室沿用真实榜单模式。

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

