# EventLens · 事件透镜

使用 Next.js App Router、React、TypeScript、Tailwind CSS 和 Motion 构建的热点浏览与 AI 分析工作台。

前端项目位于 `frontend/`，需要 Node.js 20.9 或更新版本。从 EventLens 根目录启动时，先进入前端目录。首次安装或依赖清单变更后，在 `frontend/` 运行 `npm ci`。此命令会清空并重装前端的 `node_modules`。

```bash
cd frontend
npm run dev
```

日常启动直接运行上面的命令。看到 `Ready` 后，保持终端运行并打开终端显示的 `Local` 地址，默认是 http://localhost:3000。如果该端口上的 EventLens 已经在运行，直接打开页面即可。

如果安装时出现 `ENOTFOUND registry.npmjs.org`，先恢复 npm 源的网络连接。有完整本地缓存时，可以用 `npm ci --offline --cache <缓存目录>` 恢复依赖。

在 `frontend/` 使用 `npm run typecheck` 检查类型，使用 `npm run build` 验证生产构建。

## 演示内容

- 默认打开「综合 → 微博 → 热搜榜」。微博的「同城榜」用于查看空榜单状态。
- 榜单条目为模拟数据。点击条目会打开站内阅读区，来源链接可通过工具栏在浏览器中打开。
- 点击条目右侧的对话图标可为 AI 输入框关联热点。技能可以随时切换或取消。
- 对话保留在当前页面内存中。展开与收起侧栏保留聊天历史、草稿和技能。

## 数据接入

- `frontend/src/lib/catalog.ts` 配置分类、来源、二级榜单和分析技能。
- `frontend/src/lib/api/trending.ts` 提供支持取消的 `TrendingApi.getBoard`，可替换为 FastAPI HTTP 请求。
- 后端有正文时可填写 `Trend.preview.blocks`，按顺序返回 `paragraph`（`text`）和 `image`（`src`、`alt`、可选 `caption`）。仅有摘要时填写 `Trend.preview.summary`。
- `frontend/src/lib/api/agent.ts` 提供 `AgentApi.stream`，可将 FastAPI 的 SSE 事件转换成 `AgentEvent`。请求包含问题、技能、关联热点、当前榜单和聊天历史。
- `frontend/src/mocks` 存放演示数据与回复内容，`frontend/src/hooks` 管理请求和会话状态。
