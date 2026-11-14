# EventLens · 事件透镜

使用 Next.js App Router、React、TypeScript、Tailwind CSS 和 Motion 构建的热点浏览与 AI 分析工作台。

需要 Node.js 20.9 或更新版本。首次安装或依赖清单变更后，运行 `npm ci`。此命令会清空并重装 `node_modules`。

```bash
npm run dev
```

日常启动直接运行上面的命令。看到 `Ready` 后，保持终端运行并打开终端显示的 `Local` 地址，默认是 http://localhost:3000。如果该端口上的 EventLens 已经在运行，直接打开页面即可。

如果安装时出现 `ENOTFOUND registry.npmjs.org`，先恢复 npm 源的网络连接。有完整本地缓存时，可以用 `npm ci --offline --cache <缓存目录>` 恢复依赖。

使用 `npm run typecheck` 检查类型，使用 `npm run build` 验证生产构建。

## 演示内容

- 默认打开「综合 → 微博 → 热搜榜」。微博的「同城榜」用于查看空榜单状态。
- 榜单条目为模拟数据，标题在新标签页打开平台搜索页或仓库页。
- 点击条目右侧的星标按钮可为 AI 输入框关联热点。技能可以随时切换或取消。
- 对话保留在当前页面内存中。展开与收起侧栏保留聊天历史、草稿和技能。

## 数据接入

- `src/lib/catalog.ts` 配置分类、来源、二级榜单和分析技能。
- `src/lib/api/trending.ts` 提供支持取消的 `TrendingApi.getBoard`，可替换为 FastAPI HTTP 请求。
- `src/lib/api/agent.ts` 提供 `AgentApi.stream`，可将 FastAPI 的 SSE 事件转换成 `AgentEvent`。请求包含问题、技能、关联热点、当前榜单和聊天历史。
- `src/mocks` 存放演示数据与回复内容，`src/hooks` 管理请求和会话状态。
