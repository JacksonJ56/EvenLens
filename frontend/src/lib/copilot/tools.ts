import type { AgentTool } from "@earendil-works/pi-agent-core";
import { obj, str, opt, bool } from "@earendil-works/pi-schema";
import type { Backend } from "./backend";
import { envelopeSchema } from "./contracts";
import { clipText, TOOL_RESULT_BYTES } from "./context-budget";
export const toolLabels: Record<string, string> = {
  search_hotspots: "查找相关热点",
  get_hotspot_detail: "核对热点资料",
  web_search: "搜索事件资料",
  fetch_webpage: "读取来源网页",
  get_event_trace_result: "查找已有时间线",
  trace_event: "启动事件溯源",
  get_opinion_result: "查找已有舆情报告",
  analyze_public_opinion: "启动公众评论分析",
};
function compact(v: unknown, depth = 0): unknown {
  if (depth > 7) return "[结构过深，已省略]";
  if (typeof v === "string")
    return v.length > 3500 ? v.slice(0, 3500) + "[截断]" : v;
  if (Array.isArray(v)) return v.slice(0, 12).map((x) => compact(x, depth + 1));
  if (v && typeof v === "object")
    return Object.fromEntries(
      Object.entries(v)
        .slice(0, 40)
        .map(([k, x]) => [k, compact(x, depth + 1)]),
    );
  return v;
}
function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, v]) => [key, stable(v)]),
    );
  return value;
}
export function makeTools(
  backend: Backend,
  threadId: string,
  requestId?: string,
): AgentTool[] {
  const results = new Map<
    string,
    {
      content: { type: "text"; text: string }[];
      details: { sources?: unknown[]; artifact?: unknown };
    }
  >();
  const event = obj({
    event_key: str({
      maxLength: 500,
      description: "服务端给出的完整事件标识，不可自行构造",
    }),
  });
  const analysis = obj({
    event_key: str({ maxLength: 500 }),
    refresh: opt(
      bool({ description: "仅用户明确要求重新分析时设true，默认复用结果" }),
    ),
  });
  const specs = [
    {
      name: "search_hotspots",
      description:
        "在已缓存真实热榜中按关键词查找热点，返回候选供判断；可能有歧义。",
      parameters: obj({
        query: str({ maxLength: 128 }),
        platform_id: opt(str({ maxLength: 80 })),
        feed_id: opt(str({ maxLength: 80 })),
      }),
    },
    {
      name: "get_hotspot_detail",
      description: "核对已找到热点的来源、摘要及服务端身份，记录本次讨论事件。",
      parameters: event,
    },
    {
      name: "web_search",
      description: "联网搜索事件资料或最新进展；搜索摘要不代表已阅读全文。",
      parameters: obj({ query: str({ maxLength: 128 }) }),
    },
    {
      name: "fetch_webpage",
      description:
        "使用现有安全Fetch读取公网网页正文，失败时不能假装已读，禁止内网网址。",
      parameters: obj({ url: str({ maxLength: 8192 }) }),
    },
    {
      name: "get_event_trace_result",
      description: "优先查询此事件已经完成或正在运行的时间线。",
      parameters: event,
    },
    {
      name: "trace_event",
      description:
        "必要时启动既有LangGraph事件溯源，返回后台任务或已有时间线。",
      parameters: analysis,
    },
    {
      name: "get_opinion_result",
      description: "查询微博、小红书、贴吧已有真实评论分析结果。",
      parameters: event,
    },
    {
      name: "analyze_public_opinion",
      description:
        "仅微博、小红书、贴吧：必要时用已有采集与分析模块创建后台舆情任务，需要合法有效会话。",
      parameters: analysis,
    },
  ];
  return specs.map((spec) => ({
    ...spec,
    label: toolLabels[spec.name],
    async execute(_id, params, signal) {
      const key = spec.name + JSON.stringify(stable(params));
      const cached = results.get(key);
      if (cached)
        return {
          ...cached,
          content: [
            {
              type: "text" as const,
              text:
                "本轮已经取得过相同资料，请使用已有结果，不要重复调用。\n" +
                cached.content[0].text,
            },
          ],
        };
      try {
        const result = envelopeSchema.parse(
          await backend.call(
            "tools",
            {
              thread_id: threadId,
              request_id: requestId,
              name: spec.name,
              args: params,
            },
            signal,
          ),
        );
        let text = JSON.stringify(compact(result.data));
        if (Buffer.byteLength(text) > TOOL_RESULT_BYTES)
          text = JSON.stringify({
            truncated: true,
            excerpt: clipText(text, 4000),
            note: "这是已读取资料的节选，缺失部分不能据此推断；完整分析请查看结果窗口",
          });
        const resultForModel = {
          content: [{ type: "text" as const, text }],
          details: { sources: result.sources, artifact: result.artifact },
        };
        results.set(key, resultForModel);
        return resultForModel;
      } catch (error) {
        return {
          content: [
            {
              type: "text" as const,
              text: (error instanceof Error
                ? error.message
                : "业务工具执行失败"
              ).slice(0, 600),
            },
          ],
          details: {},
          isError: true,
        };
      }
    },
  }));
}
