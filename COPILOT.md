# EventLens Copilot 开发与运行说明

## 完成的产品行为

现有右侧事件对话使用真实模型和 Pi Agent Loop。用户可直接问当前榜单、引用某条热点、连续追问，必要时由模型选择搜索、阅读、事件溯源或公众舆情工具。没有新增聊天页面，没有重写 Python 分析流程。

- 三个聊天模拟技能按钮、`mocks/agent.ts`、`SkillId`、专属样式和模拟回复已删除；实验室里的真实功能保留。
- 每次发送携带最新分区、平台、榜单。实验室手选事件和明确引用也会传入，但标题、链接、排名从 FastAPI 榜单快照重新核对。
- 切换榜单、关闭右栏不会清空对话。新建对话通过右栏顶部 `+`。
- 流式回答、工具记录、来源链接、停止、失败重试；停止聊天不代表后台分析已取消。
- 时间线/舆情报告通过消息中的结果入口打开到中部，复用原可视化组件。后台任务可在结果页单独取消。
- Copilot 舆情工具仅允许 `weibo` / `xiaohongshu` / `tieba`。原实验室能力配置不受影响。缺少登录、采集授权、搜索/模型配置时返回真实错误。

## 为什么使用这套 Pi SDK

官方资源为 [pi.dev](https://pi.dev/) 和 [Pi 仓库](https://github.com/earendil-works/pi)。本次核对时旧 `@mariozechner/pi-agent-core` 包已经标记迁移，采用当前官方 `@earendil-works/pi-agent-core`、`pi-ai`、`pi-schema` **1.6.0**，版本锁定在 package-lock 中。

`pi-agent-core` 足够提供自主工具循环、历史、流式事件和取消。没有引入完整编程 Agent，也没有注册终端、文件读写或任意代码工具。

通俗说：LLM 决定要问哪个工具，Pi 负责执行调用、把结果交回模型并继续对话，FastAPI 工具负责真正查榜单、搜索和运行原有分析。实验室仍可直接调用原有 API，所以不依赖聊天。

## 本地安装与启动

前端需 Node >=22.19.0；本机已验证 Node 23.11.0。Python 沿用现有后端环境，新增桥接没有增加 Python 依赖，也不要求新数据库。

```sh
# 终端一，从 EventLens 根目录
cd backend
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```sh
# 终端二，从 EventLens 根目录
cd frontend
npm ci
npm run dev -- --hostname 127.0.0.1 --port 3000
```

浏览器打开 http://127.0.0.1:3000。Agent 就在 Next.js 的 Node 服务端，不需要第三个服务进程。RSSHub、MediaCrawler 与平台登录保持原配置。

### 模型配置

已有 `backend/.env` 的 `EVENT_TRACE_LLM_API_KEY`、`EVENT_TRACE_LLM_BASE_URL`、`EVENT_TRACE_LLM_MODEL` 会自动复用。没有 `.env` 才从 `.env.example` 复制并填写；不要覆盖已有密钥或平台会话。

若独立选择聊天模型，可在后端 `.env` 或 Next 服务端环境设置 `COPILOT_LLM_API_KEY`、`COPILOT_LLM_BASE_URL`、`COPILOT_LLM_MODEL`。模型须支持 OpenAI-compatible Chat Completions、流式和工具调用。默认关闭 Pi thinking，DeepSeek 请求额外显式禁用 thinking；其他服务不发送 DeepSeek 专属字段。

`DEEPSEEK_API_KEY` 继续只供 Python 搜索/Fetch 使用，与聊天 LLM 凭据分离。

默认读取 `../backend/.env`。拆分部署时用 `EVENTLENS_BACKEND_ENV_FILE` 指定文件，`EVENTLENS_BACKEND_URL` 指定 FastAPI。`COPILOT_SERVICE_TOKEN` 如果显式配置，两个进程必须一致；本机未配置时从既有模型密钥派生内部凭据。任何密钥都不能改成 `NEXT_PUBLIC_*`。

### 本机 HTTPS 证书问题

若 Node 连接模型遇到 `SELF_SIGNED_CERT_IN_CHAIN`，需要配置本机可信 CA。`npm run dev` 和 `npm start` 已通过启动器先读取 `frontend/.env.local` 的证书路径，再启动 Next.js，保留 TLS 校验：

```sh
# frontend/.env.local；按实际可信证书文件填写，或使用相对于 frontend/ 的路径
NODE_EXTRA_CA_CERTS=/absolute/path/to/trusted-ca.pem
```

保存后重启前端，正常运行 `npm run dev` 即可；启动日志会显示额外 CA 已加载。启动器在子进程启动前处理该设置，因此无需每次手写环境变量前缀。显式进程环境变量优先于文件；只有证书路径被注入，不会把文件中的其他密钥一并导出。`npm run build` 不需要改启动方式。

本机已验证可用的是后端 Python CA 文件；可在 backend/ 用 `.venv/bin/python -c 'import certifi; print(certifi.where())'` 查询实际位置。更换 Python 环境后应更新路径。其他机器使用自己的可信 CA，不要设置 `NODE_TLS_REJECT_UNAUTHORIZED=0`。直接绕过 npm 脚本执行 `next dev` 时，仍需在 Node 启动前自行设置环境变量；只改 `backend/.env` 不会加载此证书配置。

## 真实源码调用链

| 实际文件 → 函数 | 输入、动作与下一个环节 |
|---|---|
| `frontend/src/components/layout/workspace.tsx` → `Workspace` | 复用 `categoryId`、`query`、`labSelection` 和 `useBoard`；构造当前页面轻量上下文，交给 `useAgent(page)`。 |
| `frontend/src/components/agent/composer.tsx` → `submit` / Enter | 读取已有输入框 draft，调用 `onSend`；热点引用保存在 Hook 的 `topic`，可移除。 |
| `frontend/src/hooks/use-agent.ts` → `send` | 读取 `latest.current` 最新页面和引用、`threadId`，建立本轮 AbortController，加入用户/助手消息。调用 `agentApi.stream`。 |
| `frontend/src/lib/api/agent.ts` → `agentApi.stream` | `POST /api/copilot/chat`，逐块解析 UTF-8 SSE；区分 delta、tool、sources、artifact、error、done，断流不能当作完成。 |
| `frontend/src/app/api/copilot/chat/route.ts` → `POST` | Zod 校验、校验本机来源；`canonicalPage` 从已有 catalog 确认分类/平台/榜单名称。`connection` 从 HttpOnly Cookie 派生 owner，并连接业务桥。 |
| `frontend/src/lib/copilot/backend.ts` → `Backend.call` | 带服务端内部凭据与浏览器 owner 请求 FastAPI `/api/copilot/begin`。浏览器不能指定 owner 或模型历史。 |
| `backend/app/copilot/api.py` → `begin` | 校验会话归属、取得本轮 lease。从 BoardService 真实快照生成热点 `event_key`、标题、排名、URL、更新时间；保存引用和讨论对象。返回独立的历史与当前页面 context。 |
| `frontend/src/lib/copilot/runtime.ts` → `runCopilot` | 创建真正的 Pi `Agent`，注入独立 Prompt、历史、最新上下文和 `makeTools`。`agent.prompt(question)` 触发 SDK 自带循环，`agent.subscribe` 推送文本和工具事件。 |
| `frontend/src/lib/copilot/tools.ts` → `makeTools` / `execute` | Pi-schema 定义参数，模型自主选择工具；通过 Backend.call 请求 `/api/copilot/tools`，同时携带 thread_id 与本轮 request_id。 |
| `backend/app/copilot/api.py` → `tools` | 重新验证会话、lease、参数、已核验事件标识及舆情平台边界，再调用下表中的既有业务。不是固定八工具顺序。 |
| `frontend/src/lib/copilot/runtime.ts` → 工具结果回调 | 工具结果给模型继续决策；只向浏览器发送简洁工具状态、来源和结构化 artifact，不显示原始大 JSON 或隐藏思考。 |
| `frontend/src/app/api/copilot/chat/route.ts` → 结尾 | 保存 SDK 历史和 UI 消息到 FastAPI `/finish`；校验本轮 lease 后才发送 done，旧请求不能覆盖新对话轮次。 |
| `frontend/src/hooks/use-agent.ts` → 事件处理 | 增量更新 messages；`ChatPanel` 显示 Markdown、工具详情、来源和结果入口。 |
| `frontend/src/components/agent/copilot-result.tsx` → `CopilotResult` | 经 Next `/api/copilot/results/{id}?thread_id=...` 读取真实状态；按 artifact.kind 复用 `EventTraceTimeline` / `PublicOpinionReport`。 |

### 工具究竟调用什么

| 工具 | 实际业务 |
|---|---|
| `search_hotspots` | `BoardService.boards` 中的已缓存真实榜单，按词过滤；有指定平台/榜单且没快照时使用已有刷新逻辑。不是全网热点搜索。 |
| `get_hotspot_detail` | 查询本会话服务端事件 registry，返回来源记录并更新 active_event。不凭模型自造 URL 启动任务。 |
| `web_search` | 原 `backend/app/event_trace/clients.py` → `TraceClients.search`，保持搜索服务和认证不变。 |
| `fetch_webpage` | 原 `TraceClients.fetch` + `public_url` / `PublicDNSResolver`，保持 SSRF 和公网 DNS 核验。 |
| `get_event_trace_result` | 查同一热点的近期任务和共享 trace cache；没有结果就返回 found=false，不启动调查。 |
| `trace_event` | `CopilotJobs.trace` 后台调用原 `state.trace_graph.ainvoke`；仍执行原 prepare / plan / search / fetch / evaluate / extract / validate / sort 节点，不重写算法。 |
| `get_opinion_result` | 精确匹配平台、榜单、热点 ID、标题、URL，复用已有实验室报告。保留原生成时间，不把历史报告当作刚采集。 |
| `analyze_public_opinion` | 原 `backend/app/public_opinion/api.py` → `create_task` → `OpinionTasks.start`，继续原 LangGraph、Deep Agents、MediaCrawler、评论分析与报告流程。 |

停止生成通过 AbortSignal → `agent.abort()`；请求断开和总超时同样触发。后台分析有独立生命周期，在中部结果页取消；复用的实验室任务不能从聊天误取消。

## 文件清单

新增：

- `frontend/src/lib/copilot/contracts.ts`：请求、SSE、来源、结果入口 Schema 与目录核对。
- `config.ts`：仅服务端读取已有模型环境配置与预算。
- `http.ts`：本机来源限制、HttpOnly 浏览器身份与错误响应。
- `backend.ts`：内部 FastAPI 客户端、超时和错误归一。
- `prompt.ts`：自然中文、指代、事实边界、工具边界与不可信内容约束。
- `tools.ts`：8 个真实 Pi 工具的参数及执行封装。
- `runtime.ts`：Pi Agent 创建、预算、流式事件、取消、历史裁剪。
- `context-budget.ts`：按模型消息估算预算、裁剪旧工具正文、保持调用/结果配对，为最终回答保留空间。
- `frontend/src/app/api/copilot/chat/route.ts`：Node SSE 入口。
- `frontend/src/app/api/copilot/threads/route.ts`：初始化/恢复会话。
- `frontend/src/app/api/copilot/results/[id]/route.ts`：结果查询与取消代理。
- `frontend/src/components/agent/copilot-result.tsx`：中部结果容器。
- `backend/app/copilot/__init__.py`、`api.py`、`store.py`：内部业务桥、后台溯源包装、会话/任务持久化。
- `backend/tests/test_copilot.py`、`frontend/tests/copilot.test.ts`：无真实模型费用的核心测试。

修改：

- `workspace.tsx`、`use-agent.ts`、`lib/api/agent.ts`、`types/agent.ts`：复用状态并替换 Mock 数据流。
- `chat-panel.tsx`、`composer.tsx`、`globals.css`、`catalog.ts`：聊天展示、停止/重试、引用，清理三个旧技能。
- `backend/app/main.py`：注册桥接、复用数据库和搜索服务、管理生命周期。
- `backend/app/event_trace/api.py`：成功调查写共享缓存，原接口独立可用。
- `frontend/package.json` / `package-lock.json`：Pi、dotenv、Zod、react-markdown 和测试工具 tsx；声明 Node 要求与 ESM。
- 前后端环境示例、README 与本文档：启动、预算和调用链说明。

删除：`frontend/src/mocks/agent.ts`。中部预览组件的删除属于前一项热榜直接外链修改，本次保留该成果。

数据库复用 `PUBLIC_OPINION_DATABASE_URL`，默认已有 SQLite；新增 `copilot_threads` 和 `copilot_jobs` 两表，启动时 create_all。聊天消息不是平台登录 Cookie，平台 Cookie 不进入会话表。

## 成本、安全和边界

- 每轮默认最多 8 次模型请求、10 次工具调用、2 次昂贵分析派发、120 秒总时限；单模型调用 40 秒、输出上限 2048，禁用默认重试。
- `COPILOT_TOKEN_BUDGET=60000` 使用模型消息和工具声明的 UTF-8 字节估算加预留输出作为 admission bound，**不是供应商结算 Token 数，也不是金额上限**。不再累计整个 Agent 对象里的重复工具注册表、UI 详情和执行元数据；真正发生的多次模型请求仍分别计入本轮预算。原 Python 分析任务仍受自己的预算控制。
- 模型保留最多最近 8 组对话、约 12 KB；旧工具正文只保留有明确截取标记的节选，超大单轮优先保留原问题与实际最终回答。UI 仍最多 80 条且约 135 KB，数据库中的聊天展示记录不会因为模型上下文裁剪而被删除。页面快照不永久拼进 SDK 历史。
- 单次工具资料默认最多约 6 KB；调用模型前按剩余预算裁剪完整旧对话组，必要时进一步缩短工具正文，保留当前问题、页面与完整工具调用/结果配对。最后一次模型调用及预算不足以继续检索时，显式设置 `toolChoice=none`，让模型基于已有资料回答，不再开启新工具循环。真实不足仍需说明，不编造结论。
- 同一轮相同工具和参数的成功结果直接复用；启动分析工具本身会查询已有结果，无需机械地先查询再启动。模型预算、上下文过长、执行超时分别提示。
- Node 日志 `Copilot usage` 包含模型次数、工具次数、字节预算/估算、峰值请求大小，以及供应商实际返回的 Token 用量，便于判断究竟触发了哪项限制。字节预算与实际 Token 用量分开统计。
- 同一 owner、同一热点近期任务优先复用；溯源缓存按 6 小时时间桶，舆情报告允许复用精确匹配的历史报告并保留生成时间。用户明确要求重新分析时才 refresh。
- Cookie 身份 + SQL owner 校验隔离本机浏览器会话；同一轮 lease 校验阻止过期工具与迟到保存。该功能限定 localhost/127.0.0.1；**不是多用户生产账户权限系统**。
- 不支持跨机器/多进程分布式任务恢复。后端重启将未完成聊天溯源标为 interrupted，由用户明确重试；不会自动花费额度重跑。
- 网页抓取和平台登录限制仍然存在，不绕过验证。公开搜索不等于登录后的平台全文读取。

## 验证方法与结果

```sh
# frontend/
npm run test:copilot
npm run typecheck
npm run build
# backend/
.venv/bin/python -m unittest discover -s tests
```

测试替身只存在于测试代码，不是生产 fallback。Mock 模型测试验证 SDK 消息/工具传递和状态控制，不证明任何真实模型永远能正确识别语义。

真实验收可按此操作：

1. 打开微博热搜，直接问“第一条是什么？”——只应使用快照，避免启动昂贵分析。
2. 追问“原文链接是什么？”——保留前一轮对象；热搜原文可能实际是关键词搜索页，不能冒充正文。
3. 点击某条热点的添加按钮，输入问题；引用能移除，切换榜单后历史保留，每次发送页面提示更新。
4. 明确要求“梳理完整来龙去脉”或“分析微博网友态度”时，工具应先查已有结果，必要时创建后台任务并提供结果入口。
5. 询问抖音/知乎完整舆情时，说明暂不支持，不生成评论统计。
6. 运行中停止回答，再重试；已经创建的后台分析到中部单独查看/取消。

本次实际联网验证包含当前真实微博榜首、连续追问及来源、服务端历史保存和跨浏览器 404 隔离；浏览器验证了桌面和 390px 移动布局、引用添加/移除、侧栏收起恢复、刷新恢复历史。失败重试、停止和最新平台上下文用浏览器隔离测试夹具验证。没有在自动测试里默认重跑完整付费溯源或在线评论采集；这两类新调度通过 Mock 业务回归验证，实际成功仍依赖已有 API、预算及平台会话。

项目未配置 ESLint 脚本，本次不声称运行了不存在的 lint 命令。

### 最终检查记录

- 后端完整回归：**144 项通过**（含新增 15 项桥接测试）。
- 前端 Pi/SSE/上下文/预算核心测试：**17 项通过**。
- `npm run typecheck`、`npm run build`、`git diff --check` 通过。
- 浏览器隔离夹具：重试、停止、切换平台上下文、结果窗口、移动端及实验室入口通过。测试文件 `frontend/tests/copilot_browser.py`，在已有 Playwright 的 Python 环境执行：

  ```sh
  python frontend/tests/copilot_browser.py
  ```

- 真实模型额外验证：实际调用 `get_hotspot_detail`，返回工具开始/完成及可追溯来源，没有启动溯源或舆情任务。
- 两项完整分析的新增聊天派发经过 Mock 业务接口回归；本轮没有为验收重新消耗完整调查/评论采集额度，不能将其记作新的真实采集成功。

## 清空当前聊天记录

右侧事件对话顶部的垃圾桶按钮用于清空当前会话。确认后调用 `useAgent.clearHistory` → Next `DELETE /api/copilot/threads?id=...` → FastAPI `clear_thread_history` → `CopilotStore.clear_history`，同时清除持久化 UI 消息、SDK 历史和已讨论事件上下文，刷新也不会恢复。

当前 thread_id、输入草稿和待发送引用保留；热榜选择、已生成报告及后台任务保留。生成回答时禁用清空；后端也用会话归属和 lease 校验阻止处理中的会话被清空，并防止迟到结果恢复旧消息。请求失败时保留现有记录并显示错误。取消确认不发送删除请求。

## Copilot 预算频繁触发修复

旧版在每次模型调用前统计整个 AgentContext，包含模型不会读取的运行时/界面详情，并允许历史工具正文占据约 50 KB。即使提高总预算，长会话仍可能在工具返回后没有空间生成回答。

现改为 `context-budget.ts` 仅估算模型消息与工具声明、动态裁剪完整旧对话组及工具正文、保留当前问题和调用/结果配对；接近预算或调用次数上限时进入禁止继续调用工具的最终回答阶段。同一轮相同参数的成功工具结果直接复用。保留原字节预算配置及上限，没有修改本机 `.env`。

本次检查：23 项前端核心测试、TypeScript、生产构建及浏览器回归通过。使用原隔离测试会话完成真实详情工具查询和两次连续追问，全部成功，未清空历史，也未启动完整溯源或评论采集任务。
