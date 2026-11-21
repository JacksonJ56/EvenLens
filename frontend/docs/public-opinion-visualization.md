# EventLens 舆情报告可视化

沿用现有三栏工作台与 Recharts 3。报告按实际数据出现模块；原始评论仍由后端保存，前端不会调用 LLM 生成数字或组件。

## 实际调用链

1. `backend/app/public_opinion/analysis.py::CommentAnalysis.analyze()` 让模型给出分类与评论引用，程序记录 `Section.analyzed_sample` 和 `data[].evidence`；情绪未分类记录归入“无法判断”，主题可以重叠。立场必须附带 `issue`。
2. `workflow.py::validate_report()` 验证引用和统计分母，随后 `visualization.py::enrich_report()` 从保存的一级评论及已核验归属重新计算数量/占比，调用 `discussion_metrics.py::discussion_metrics()` 计算可解释的样本特征。
3. `api.py::task_report()` 也会对旧报告执行只读统计投影，返回 `OpinionReport.charts / context_timeline / visualization_notes`，不重新研究。图表点携带统计分母、精确评论引用、定义、时间范围等。
4. `frontend/src/components/event-lab/public-opinion-report.tsx` 按模块组织报告；`opinion-charts/visualization-registry.tsx` 将后端 type 映射到固定 React 组件。图表代码懒加载，只使用一个 Recharts 库。
5. 点选图形或键盘图例 → `comment-drilldown.tsx` → `GET /api/public-opinion/tasks/{id}/chart-comments?chart_id=...&point_id=...` → 后端按这一个数据点实际计数的评论 ID 查询、分页返回；切换筛选会取消旧请求。

## 可信统计口径

| 图表 | 数据与条件 |
| --- | --- |
| EmotionDistributionChart | 已完成分类批次为分母，无法判断不排除。数量/占比由真实归属计算 |
| DiscussionTopicsChart | 按评论数量降序，多重归属不去除，不使用饼图，不要求占比和为 100% |
| StanceComparisonChart | 每个明确 issue 一张堆叠图，标签来自实际分类；多个议题可分别显示，不创造正反两派 |
| CommentTimelineChart | 实际带时区发布时间；至少 6 条、时间覆盖率 ≥80%、至少 3 个时段。图中绘制**全部**真实时间点；列表可折叠。不补零，不补虚构点 |
| DiscussionRadarChart | 至少 20 条实际完成分析的一级评论；至少三项有定义、共同分母的比例指标，且有非零观测。0–100% 固定量纲；可切换柱状图，非零指标少于三个时默认柱状图 |
| PostContributionChart | 每个帖子实际保留的一级评论数量，不是平台总评论量，回复不混入 |
| ContextualTimeline | 关联必须有已读来源与覆盖来源 ID 的证据；抓取时刻、帖子发布时间、资料发布日期、未知关联时间区分显示。跨时区按实际时刻排序，未知时间置后 |

雷达指标固定由 Python 计算，**不是 AI 评分**：

- 含问号文本：清洗后包含 `?` 或 `？`，不等同质疑/真实疑问。
- 较长文本：清洗、去首尾空白后不少于 50 个 Unicode 字符，不等同评论质量。
- 同文重复：当前已分析样本内清洗文本完全相同且出现至少两次，所有真实评论都保留，不判断水军/机器人。
- 获赞评论：采集时点赞数 >0；仅当所有样本都提供可靠点赞数才加入，缺失值不当作 0。

每项占比 = 满足条件的实际一级评论数 ÷ 本图实际已分析样本数 ×100%，保留一位小数。指标可重叠，不相加为 100%。Schema 校验定义、引用数量、共同分母、量纲与计算结果。不接受“影响力80分”等模型自由分数；无足够数据不输出雷达图。

部分报告会说明哪些模块已有可信统计、哪些未产生；没有情绪分类时不从主题或点赞数推测情绪。数据条数全部分析完成，也不意味着每个分析维度都完成。每个图表区域占一行，宽度足够时内部采用图表 43% / 解读 57%，不足时上下排列，保留原有导航及右侧聊天。

## 本次增量文件

| 文件（相对项目根目录） | 变更 | 职责 |
| --- | --- | --- |
| backend/app/public_opinion/discussion_metrics.py | 新增 | 固定定义的样本文本/互动占比与评论依据 |
| backend/app/public_opinion/schemas.py | 修改 | 雷达定义、共同量纲校验、有评论帖子数、时间线帖子引用 |
| backend/app/public_opinion/visualization.py | 修改 | 指标生成、缺失模块说明、实际贡献帖子数、跨时区与背景证据校验 |
| frontend/src/types/public-opinion.ts | 修改 | 可扩展图表与指标定义类型 |
| frontend/src/components/event-lab/report-coverage.tsx | 新增 | 部分完成、缺失模块与数据不足说明 |
| frontend/src/components/event-lab/public-opinion-report.tsx | 修改 | 第一屏图表顺序、有效帖子概况、模块组织 |
| frontend/src/components/event-lab/public-opinion-report.module.css | 修改 | 模块状态和说明样式 |
| frontend/src/components/event-lab/opinion-charts/chart-plots.tsx | 修改 | 真正的立场堆叠图、雷达与百分比柱状图 |
| frontend/src/components/event-lab/opinion-charts/visualization-registry.tsx | 修改 | 雷达注册、展示方式切换、完整时间/立场绘图、最新数据点状态 |
| frontend/src/components/event-lab/opinion-charts/opinion-charts.module.css | 修改 | 单图宽度与切换控件样式 |
| frontend/src/components/event-lab/opinion-charts/contextual-timeline.tsx | 修改 | 原始帖子/热点来源链接 |
| backend/tests/test_opinion_visualization.py | 修改 | 雷达真实计数、归一化、缺失点赞、分析分母、时区与弱证据测试 |
| backend/tests/visualization_fixture.py | 新增 | 标记 TEST 的完整结构化报告，经真实校验和统计生成 |
| backend/tests/serve_opinion_fixture.py | 修改 | 独立临时 TEST 服务，绝不被 app.main 引用 |
| frontend/tests/opinion_visualizations_browser.py | 修改 | 真实报告与 TEST 完整报告两种验收，覆盖完整曲线和新增图形交互 |
| frontend/docs/public-opinion-visualization.md | 新增 | 本文协议、规则、文件清单和运行说明 |

原有统计口径、`palette.ts` 和平台登录代码复用。未增加依赖、环境变量或数据库表。

## 总体评价优先与紧凑证据浏览（2026-11-19）

报告顺序：标题与来源 → AI 总体评价（含核心判断、关键发现）→ 紧凑数据概况 → 主题、情绪图文分析 → 立场与其他实际研究模块 → 宏观关联 → 时间/贡献/特征辅助图 → 折叠评论入口 → 覆盖与局限。

唯一总评字段是 `OpinionReport.overall_assessment`，不新增语义重复的 `executive_summary`。旧 `insight` 仅作为反序列化兼容入口，不再输出：旧的真实摘要标记 `legacy`，两种已知模板占位文字转为 `unavailable`，不会为了字数补写。新报告包含：

```text
overall_assessment:
  summary / core_judgment / key_findings
  section_types / evidence[{post_id, comment_id}] / source_ids
  status(completed, partial, legacy, unavailable) / reason
chart_interpretations[]:
  chart_id / analysis / evidence / source_ids
```

真实生成链：`research.py::OpinionResearch.investigate()` 完成工具研究、宏观资料引用核对和真实代表评论整理 → `visualization.py::enrich_report()` 计算可核验图表 → `assessment.py::synthesize_assessment()` 使用同一模型、同一任务预算做一次结构化综合写作 → `workflow.py::validate_report()` 再校验来源和引用 → 存储报告 → `api.py::task_report()` → `PublicOpinionReport` → `OverallAssessmentView` / `ChartAnalysis`。

`prompts.py::ASSESSMENT` 要求正常证据下约 200–350 字综合判断，资料不足则缩短，不把图表数字换句话重复。提供的是有上限的真实分析、评论摘录、实际统计、已读背景资料与局限；不是整库评论。`assessment.py` 验证引用、已执行模块及统计叙述，单个图表解读失败不会删除独立通过校验的总评。研究阶段在原预算内预留一次模型调用和最多 24,000 Token 的准入空间用于最后综合，不增加总预算，也不把预留量算成实际消费。模型/预算/证据不足时明确标记 unavailable，保留已有模块。GET 报告不调用模型、不自动改写历史研究。

评论入口默认关闭，首次展开才请求；每页 3 条、最多两行预览，全文只有点开单条后才读取。容器最大宽度 660px，展开内容最高 390px 内滚动。图表点击、总体评价、观点/争议分组均使用同一个证据浏览器，保留真实帖子/评论 ID、原始顺序、时间与链接。

| 本轮文件 | 职责 |
| --- | --- |
| backend/app/public_opinion/schemas.py | 总评、图表解读、历史字段兼容 |
| backend/app/public_opinion/assessment.py（新） | 有界综合输入、模型调用、缓存及引用/统计校验 |
| backend/app/public_opinion/prompts.py | 研究后综合写作指令 |
| backend/app/public_opinion/llm.py、research.py、workflow.py | 原预算内预留、研究后生成、保存与报告校验 |
| backend/app/public_opinion/api.py | `/evidence` 按模块/分组/总评/图表分页；`/chart-comments?preview=true` 返回预览；`/comments` 读取单条全文 |
| frontend/src/types/public-opinion.ts | 对应 TypeScript 协议 |
| frontend/src/components/event-lab/public-opinion-report.tsx、同名 CSS | 报告顺序、紧凑数据、折叠代表评论 |
| frontend/src/components/event-lab/overall-assessment.tsx（新） | 总评、核心判断、关键发现及证据入口 |
| frontend/src/components/event-lab/evidence-browser.tsx、同名 CSS（新） | 折叠、分页、两行预览、按需全文、取消旧请求和重试 |
| frontend/src/components/event-lab/opinion-charts/chart-analysis.tsx（新） | 图表实际综合解读及历史分析降级 |
| frontend/src/components/event-lab/opinion-charts/visualization-registry.tsx、opinion-charts.module.css、comment-drilldown.tsx | 43/57 图文布局、紧凑证据联动 |
| backend/tests/test_opinion_assessment.py（新）、test_public_opinion.py | 综合输入、缓存、引用、统计、失败、预算及接口回归 |
| backend/tests/visualization_fixture.py、frontend/tests/opinion_visualizations_browser.py | 独立 TEST 完整场景与保存的真实报告浏览器验收 |

最新验收：115 项后端测试通过；TypeScript 和 Next.js 生产构建通过。保存的真实小红书 50 条评论研究使用其剩余预算生成 330 字总体评价、4 段图表解读，并通过引用校验；仍标记部分完成，没有重新搜索或采集。历史报告若未生成综合分析，显示真实缺失状态，不声称它拥有新结论。

浏览器分别验证真实报告与独立 TEST 报告：总评在指标之前、默认无评论请求、两行预览、全文按需读取、每页 3 条、图表点击/键盘联动、错误重试、桌面图文比例、390px 窄屏及深浅主题。TEST 场景补齐情绪、立场、宏观证据路径，不能作为真实研究结论。

## 验证和运行

正常启动沿用已有配置：

```sh
cd backend
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 另一个终端
cd frontend
npm run dev -- --port 3100
```

测试：

```sh
cd backend
./.venv/bin/python -m unittest discover -s tests -q
cd ../frontend
npm run typecheck
npm run build
```

真实保存报告的浏览器验收（不重跑 Agent）：

```sh
/path/to/MediaCrawler/.venv/bin/python \
  frontend/tests/opinion_visualizations_browser.py \
  --base http://127.0.0.1:3100 --task <真实已完成任务ID>
```

完整合成场景需手动启动测试服务，随后使用它返回的 TEST ID：

```sh
cd backend
./.venv/bin/python -m uvicorn tests.serve_opinion_fixture:app --host 127.0.0.1 --port 8002
# GET http://127.0.0.1:8002/test-case 获取 task_id
# 从项目根目录执行：
/path/to/MediaCrawler/.venv/bin/python \
  frontend/tests/opinion_visualizations_browser.py \
  --base http://127.0.0.1:3100 --api-base http://127.0.0.1:8002 --task <TEST任务ID>
```

浏览器测试只回放任务创建和登录状态，不收费执行；真实报告和评论接口仍走真实本机后端。合成报告不进入正式服务，不能将其视为真实研究结果。
