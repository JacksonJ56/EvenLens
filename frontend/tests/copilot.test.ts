import { test } from "node:test";
import assert from "node:assert/strict";
import type { AssistantMessage, JsonObject } from "@earendil-works/pi-ai";
import { AssistantMessageEventStream } from "@earendil-works/pi-ai/utils/event-stream";
import type { StreamFn } from "@earendil-works/pi-agent-core";
import { runCopilot, trimHistory } from "../src/lib/copilot/runtime";
import { Backend } from "../src/lib/copilot/backend";
import { canonicalPage, requestSchema } from "../src/lib/copilot/contracts";
import type { CopilotConfig } from "../src/lib/copilot/config";
import type { AgentEvent } from "../src/types/agent";

const config: CopilotConfig = {
  key: "TEST_SECRET",
  model: "TEST",
  baseUrl: "https://example.com/v1",
  backend: "http://test",
  serviceToken: "TEST_INTERNAL",
  maxTools: 10,
  maxRequests: 8,
  tokenBudget: 100000,
  timeoutMs: 1000,
};
const item = {
  event_key: "weibo/hot/e1",
  id: "e1",
  title: "测试事件A",
  rank: 1,
  url: "https://example.com/a",
};
const context = {
  page: { platform_id: "weibo", feed_id: "hot" },
  items: [item],
  reference: null,
  active_event: null,
  marker: "PAGE_SNAPSHOT_MARKER",
};
type Reply = {
  text?: string;
  tool?: { name: string; args: JsonObject };
  delay?: number;
  fail?: boolean;
};
function fake(decide: (messages: unknown[], call: number) => Reply): StreamFn {
  let call = 0;
  return (model, ctx, options) => {
    const stream = new AssistantMessageEventStream();
    const reply = decide(ctx.messages, ++call);
    const message: AssistantMessage = {
      role: "assistant",
      api: "openai-completions",
      provider: "eventlens",
      model: model.id,
      content: [],
      usage: {
        input: 1,
        output: 1,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 2,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
      },
      stopReason: "stop",
      timestamp: Date.now(),
    };
    queueMicrotask(
      () =>
        void (async () => {
          stream.push({ type: "start", partial: message });
          stream.push({
            type: "thinking_delta",
            contentIndex: 0,
            delta: "HIDDEN_REASONING_TEST",
            partial: message,
          });
          if (reply.delay) await new Promise((r) => setTimeout(r, reply.delay));
          if (options?.signal?.aborted || reply.fail) {
            message.stopReason = options?.signal?.aborted ? "aborted" : "error";
            message.errorMessage = "TEST upstream";
            stream.push({
              type: "error",
              reason: message.stopReason,
              error: message,
            });
            return;
          }
          if (reply.tool) {
            message.content = [
              {
                type: "toolCall",
                id: "tc_" + call,
                name: reply.tool.name,
                arguments: reply.tool.args,
              },
            ];
            message.stopReason = "toolUse";
          } else {
            message.content = [{ type: "text", text: reply.text ?? "" }];
            stream.push({
              type: "text_delta",
              contentIndex: 0,
              delta: reply.text ?? "",
              partial: message,
            });
          }
          stream.push({
            type: "done",
            reason: message.stopReason as "stop" | "toolUse",
            message,
          });
        })(),
    );
    return stream;
  };
}
function backend(
  handler: (body: Record<string, unknown>) => unknown | Promise<unknown>,
) {
  const calls: Record<string, unknown>[] = [];
  return {
    calls,
    value: {
      call: async (_path: string, body: Record<string, unknown>) => {
        calls.push(body);
        return handler(body);
      },
    } as unknown as Backend,
  };
}
const input = {
  question: "热榜第一条是什么",
  context,
  history: [],
  threadId: "a".repeat(32),
};
async function run(
  stream: StreamFn,
  service = backend(() => ({ data: { found: false } })),
  options: Partial<CopilotConfig> = {},
  signal = new AbortController().signal,
) {
  const events: AgentEvent[] = [];
  const result = await runCopilot(
    input,
    { ...config, ...options },
    service.value,
    (e) => events.push(e),
    signal,
    stream,
  );
  return { result, events, service };
}

test("当前榜单第一条直接回答，流式文本不泄露隐藏思考或密钥", async () => {
  const { result, events, service } = await run(
    fake((messages) => {
      assert.match(JSON.stringify(messages), /测试事件A/);
      return { text: "当前第一条是测试事件A。" };
    }),
  );
  assert.equal(result.answer, "当前第一条是测试事件A。");
  assert.equal(service.calls.length, 0);
  assert.equal(result.status, "done");
  assert.ok(events.some((e) => e.type === "delta"));
  assert.doesNotMatch(
    JSON.stringify(events),
    /HIDDEN_REASONING_TEST|TEST_SECRET/,
  );
  assert.doesNotMatch(JSON.stringify(result.history), /PAGE_SNAPSHOT_MARKER/);
});
test("明确引用与当前榜单独立传入，不在客户端按关键词强行匹配", async () => {
  const events: AgentEvent[] = [];
  const referenced = {
    ...context,
    reference: { ...item, title: "明确引用事件B" },
  };
  const result = await runCopilot(
    { ...input, context: referenced },
    config,
    backend(() => ({ data: {} })).value,
    (e) => events.push(e),
    new AbortController().signal,
    fake((messages) => {
      assert.match(JSON.stringify(messages), /明确引用事件B/);
      return { text: "你引用的是事件B。" };
    }),
  );
  assert.match(result.answer, /事件B/);
});
test("连续追问、切换榜单后仍保留历史对象与当前页面区分", async () => {
  const first = await run(fake(() => ({ text: "我们正在讨论事件A。" })));
  const result = await runCopilot(
    {
      ...input,
      question: "后来呢",
      history: first.result.history,
      context: {
        ...context,
        page: { platform_id: "baidu", feed_id: "hot" },
        items: [{ ...item, title: "当前新榜单事件C" }],
        active_event: item,
      },
    },
    config,
    backend(() => ({ data: {} })).value,
    () => undefined,
    new AbortController().signal,
    fake((messages) => {
      const text = JSON.stringify(messages);
      assert.match(text, /我们正在讨论事件A/);
      assert.match(text, /当前新榜单事件C/);
      assert.match(text, /active_event/);
      return { text: "继续说刚才的事件A。" };
    }),
  );
  assert.match(result.answer, /事件A/);
});
test("多个相似候选可以澄清，不调用昂贵工具", async () => {
  const service = backend(() => {
    throw Error("No analysis expected");
  });
  const result = await runCopilot(
    {
      ...input,
      question: "汽车事故怎么回事",
      context: {
        items: [{ title: "品牌A汽车事故" }, { title: "品牌B汽车事故" }],
      },
    },
    config,
    service.value,
    () => undefined,
    new AbortController().signal,
    fake(() => ({ text: "你指品牌A还是品牌B的事故？" })),
  );
  assert.match(result.answer, /还是/);
  assert.equal(service.calls.length, 0);
});
test("实际Pi循环由模型选择先查询后启动溯源，任务与资料进入独立UI事件", async () => {
  const artifact = {
    id: "b".repeat(32),
    kind: "trace",
    status: "queued",
    title: "测试事件A",
    message: "已排队",
    created_at: 1,
  };
  const service = backend((body) =>
    body.name === "get_event_trace_result"
      ? { data: { found: false } }
      : {
          data: { artifact },
          artifact,
          sources: [{ title: "原文", url: "https://example.com/a" }],
        },
  );
  const { result, events } = await run(
    fake((_messages, call) =>
      call === 1
        ? {
            tool: {
              name: "get_event_trace_result",
              args: { event_key: item.event_key },
            },
          }
        : call === 2
          ? {
              tool: {
                name: "trace_event",
                args: { event_key: item.event_key },
              },
            }
          : { text: "已启动时间线分析，可以查看真实进度。" },
    ),
    service,
  );
  assert.deepEqual(
    service.calls.map((c) => c.name),
    ["get_event_trace_result", "trace_event"],
  );
  assert.equal(result.artifacts.length, 1);
  assert.ok(events.some((e) => e.type === "artifact"));
  assert.ok(events.some((e) => e.type === "sources"));
  assert.equal(result.status, "done");
});
test("不支持的平台工具失败反馈给模型，而不是伪造成功", async () => {
  const service = backend(() => {
    throw new Error("Copilot 舆情仅支持微博、小红书、贴吧");
  });
  const { result, events } = await run(
    fake((_m, c) =>
      c === 1
        ? {
            tool: {
              name: "analyze_public_opinion",
              args: { event_key: "douyin/hot/e1" },
            },
          }
        : { text: "目前不支持抖音完整评论分析。" },
    ),
    service,
  );
  assert.match(result.answer, /不支持抖音/);
  assert.equal(result.artifacts.length, 0);
  assert.ok(events.some((e) => e.type === "tool" && e.tool.status === "error"));
});
test("SDK校验工具参数，不开放Shell或任意文件工具", async () => {
  const service = backend(() => ({ data: {} }));
  const { events } = await run(
    fake((_m, c) =>
      c === 1
        ? {
            tool: {
              name: "fetch_webpage",
              args: { url: "https://example.com/", shell: "rm -rf" },
            },
          }
        : { text: "工具参数无效。" },
    ),
    service,
  );
  assert.equal(service.calls.length, 0);
  assert.ok(events.some((e) => e.type === "tool" && e.tool.status === "error"));
});
test("主动取消后状态正确，不会把取消显示成完成", async () => {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 15);
  const { result, events } = await run(
    fake(() => ({ text: "not completed", delay: 40 })),
    undefined,
    {},
    controller.signal,
  );
  assert.equal(result.status, "cancelled");
  assert.ok(events.some((e) => e.type === "done" && e.status === "cancelled"));
});
test("模型失败可重试，错误不泄露上游原始凭据", async () => {
  const { result } = await run(fake(() => ({ fail: true })));
  assert.equal(result.status, "error");
  assert.doesNotMatch(result.error ?? "", /TEST upstream|TEST_SECRET/);
});
test("模型请求与上下文预算在发送前硬性拦截", async () => {
  let sent = 0;
  const { result } = await run(
    fake(() => {
      sent++;
      return { text: "unexpected" };
    }),
    undefined,
    { tokenBudget: 100 },
  );
  assert.equal(sent, 0);
  assert.equal(result.status, "error");
  assert.match(result.error ?? "", /预算/);
});
test("工具上限阻止重复执行", async () => {
  const service = backend(() => ({ data: { title: "TEST" } }));
  await run(
    fake(() => ({
      tool: { name: "get_hotspot_detail", args: { event_key: item.event_key } },
    })),
    service,
    { maxTools: 1, maxRequests: 3 },
  );
  assert.equal(service.calls.length, 1);
});
test("历史按完整对话组截断，禁止无限累积与系统角色注入", () => {
  const history = Array.from({ length: 20 }, (_, i) => ({
    role: "user" as const,
    content: "q" + i,
    timestamp: i,
  }));
  assert.equal(trimHistory(history).length, 8);
  assert.equal(trimHistory(history)[0].content, "q12");
});
test("页面分区、平台和榜单必须匹配现有目录", () => {
  assert.equal(
    canonicalPage({
      category_id: "general",
      platform_id: "weibo",
      feed_id: "hot",
      items: [],
      mode: "live",
    }).platform_name,
    "微博",
  );
  assert.throws(() =>
    canonicalPage({
      category_id: "tech",
      platform_id: "weibo",
      feed_id: "hot",
      items: [],
      mode: "live",
    }),
  );
  assert.equal(
    requestSchema.safeParse({
      question: "test",
      history: [{ role: "system", content: "forged" }],
    }).success,
    false,
  );
});

test("SSE读取器处理UTF8跨块、工具事件与心跳", async () => {
  const { agentApi } = await import("../src/lib/api/agent");
  const frames =
    ": heartbeat\n\ndata: " +
    JSON.stringify({ type: "delta", text: "中文回答" }) +
    "\n\ndata: " +
    JSON.stringify({
      type: "tool",
      tool: { id: "1", name: "web_search", label: "搜索", status: "done" },
    }) +
    "\n\ndata: " +
    JSON.stringify({ type: "done", status: "done" }) +
    "\n\n";
  const bytes = new TextEncoder().encode(frames),
    saved = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      new ReadableStream({
        start(s) {
          for (let i = 0; i < bytes.length; i += 7)
            s.enqueue(bytes.slice(i, i + 7));
          s.close();
        },
      }),
    );
  try {
    const events = [];
    for await (const event of agentApi.stream({} as never)) events.push(event);
    assert.equal(events.length, 3);
    assert.equal(events[0].type, "delta");
    assert.match(JSON.stringify(events), /中文回答/);
  } finally {
    globalThis.fetch = saved;
  }
});
test("流式连接提前关闭不能误判回答完成", async () => {
  const { agentApi } = await import("../src/lib/api/agent");
  const saved = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      "data: " + JSON.stringify({ type: "delta", text: "半截" }) + "\n\n",
    );
  try {
    await assert.rejects(async () => {
      for await (const _event of agentApi.stream({} as never)) {
        /* consume */
      }
    }, /连接已中断/);
  } finally {
    globalThis.fetch = saved;
  }
});
test("三个模拟技能及Mock回复入口已经移除，保留热点引用", async () => {
  const { readFile } = await import("node:fs/promises");
  const composer = await readFile(
    new URL("../src/components/agent/composer.tsx", import.meta.url),
    "utf8",
  );
  const hook = await readFile(
    new URL("../src/hooks/use-agent.ts", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(
    composer + hook,
    /getSkill|SkillId|skill-shortcuts|mockReply|角色与背景|争议与观点|脉络重建/,
  );
  assert.match(composer, /onClearTopic/);
  assert.match(hook, /latest.current/);
});

test("总执行超时与用户主动停止区分展示", async () => {
  const controller = new AbortController();
  setTimeout(() => controller.abort(new Error("COPILOT_TIMEOUT")), 10);
  const { result } = await run(
    fake(() => ({ text: "not completed", delay: 25 })),
    undefined,
    {},
    controller.signal,
  );
  assert.equal(result.status, "error");
  assert.match(result.error ?? "", /时限/);
});

test("旧会话中的长工具正文和UI详情会被精简，不会挤掉当前问题", async () => {
  const first = await run(fake(() => ({ text: "继续讨论测试事件A。" })));
  const user = first.result.history[0];
  const assistant = first.result.history.find((m) => m.role === "assistant");
  assert.ok(assistant?.role === "assistant");
  const legacy = [
    user,
    {
      ...assistant,
      content: [
        {
          type: "toolCall" as const,
          id: "old_call",
          name: "fetch_webpage",
          arguments: { url: "https://example.com/a" },
        },
      ],
    },
    {
      role: "toolResult" as const,
      toolCallId: "old_call",
      toolName: "fetch_webpage",
      timestamp: 1,
      isError: false,
      content: [{ type: "text" as const, text: "历史原文".repeat(12000) }],
      details: { duplicate: "HUGE_UI_DETAILS".repeat(12000) },
    },
    assistant,
  ];
  const events: AgentEvent[] = [];
  const service = backend(() => ({
    data: {
      title: "真实来源",
      url: "https://example.com/a",
      content: "读取内容".repeat(12000),
    },
  }));
  const result = await runCopilot(
    { ...input, question: "后来呢？请查最新资料", history: legacy },
    { ...config, tokenBudget: 60000 },
    service.value,
    (e) => events.push(e),
    new AbortController().signal,
    fake((messages, call) => {
      assert.doesNotMatch(JSON.stringify(messages), /HUGE_UI_DETAILS/);
      return call === 1
        ? {
            tool: {
              name: "fetch_webpage",
              args: { url: "https://example.com/a" },
            },
          }
        : { text: "已读取来源节选，现有资料只能支持这些信息。" };
    }),
  );
  assert.equal(result.status, "done");
  assert.equal(service.calls.length, 1);
  assert.ok(result.usage.estimated_input_and_output_upper_bound <= 60000);
  assert.ok(Buffer.byteLength(JSON.stringify(result.history)) <= 12000);
  assert.ok(
    events.some((e) => e.type === "sources") || result.answer.includes("节选"),
  );
});

test("最后一次模型请求保留给最终回答，不会把全部次数耗在工具循环", async () => {
  const { result, service } = await run(
    fake((messages, call) => {
      if (call === 1)
        return {
          tool: {
            name: "get_hotspot_detail",
            args: { event_key: item.event_key },
          },
        };
      assert.match(
        JSON.stringify(messages),
        /现在必须直接根据已有资料回答用户/,
      );
      return { text: "根据已取得的资料，目前只能确认标题和来源。" };
    }),
    undefined,
    { maxRequests: 2 },
  );
  assert.equal(result.status, "done");
  assert.equal(result.usage.model_requests, 2);
  assert.equal(service.calls.length, 1);
});

test("相同工具参数只实际执行一次，避免重复检索消耗预算", async () => {
  const service = backend(() => ({
    data: { title: "测试事件A", url: "https://example.com/a" },
  }));
  const { result } = await run(
    fake((messages, call) =>
      call < 3
        ? {
            tool: {
              name: "get_hotspot_detail",
              args: { event_key: item.event_key },
            },
          }
        : (assert.match(JSON.stringify(messages), /本轮已经取得过相同资料/),
          { text: "已根据现有资料作答。" }),
    ),
    service,
  );
  assert.equal(service.calls.length, 1);
  assert.equal(result.status, "done");
});

test("裁剪后仍保留完整工具调用与结果配对、原始问题和当前快照", async () => {
  const { fitContext, requestBytes } = await import(
    "../src/lib/copilot/context-budget"
  );
  const first = await run(fake(() => ({ text: "旧回答" })));
  const assistant = first.result.history.find((m) => m.role === "assistant");
  assert.ok(assistant?.role === "assistant");
  const snapshot = {
    role: "user" as const,
    content: "CURRENT_PAGE_UNCHANGED",
    timestamp: 2,
  };
  const question = {
    role: "user" as const,
    content: "CURRENT_QUESTION_UNCHANGED",
    timestamp: 3,
  };
  const pair = {
    ...assistant,
    content: [
      {
        type: "toolCall" as const,
        id: "paired",
        name: "fetch_webpage",
        arguments: { url: "https://example.com/path" },
      },
    ],
  };
  const response = {
    role: "toolResult" as const,
    toolCallId: "paired",
    toolName: "fetch_webpage",
    content: [{ type: "text" as const, text: "内容".repeat(10000) }],
    isError: false,
    timestamp: 4,
    details: { large: "discard".repeat(10000) },
  };
  const packed = fitContext(
    [
      ...Array.from({ length: 8 }, (_, i) => ({
        role: "user" as const,
        content: "历史".repeat(1000),
        timestamp: i,
      })),
      snapshot,
      question,
      pair,
      response,
    ],
    snapshot,
    10000,
    false,
  );
  assert.ok(packed.bytes <= 10000);
  assert.equal(packed.bytes, requestBytes(packed.messages));
  assert.ok(packed.messages.includes(snapshot));
  assert.ok(packed.messages.includes(question));
  assert.deepEqual(
    packed.messages.find((m) => m.role === "assistant")?.content,
    pair.content,
  );
  assert.ok(
    packed.messages.some(
      (m) => m.role === "toolResult" && m.toolCallId === "paired",
    ),
  );
  assert.doesNotMatch(JSON.stringify(packed.messages), /discard/);
});

test("总预算接近上限时提前进入最终回答，不是在工具完成后突然报错", async () => {
  const { result } = await run(
    fake((messages, call) =>
      call === 1
        ? {
            tool: {
              name: "get_hotspot_detail",
              args: { event_key: item.event_key },
            },
          }
        : (assert.match(
            JSON.stringify(messages),
            /现在必须直接根据已有资料回答用户/,
          ),
          { text: "根据已取得资料，暂时只能确认该热点标题。" }),
    ),
    undefined,
    { tokenBudget: 30000 },
  );
  assert.equal(result.status, "done");
  assert.ok(result.usage.estimated_input_and_output_upper_bound <= 30000);
});

test("超大单轮历史保留最后问题和实际回答，工具配对整体移除", async () => {
  const first = await run(
    fake(() => ({ text: "最后确认的讨论对象仍是事件A。" })),
  );
  const assistant = first.result.history.find((m) => m.role === "assistant");
  assert.ok(assistant?.role === "assistant");
  const group = [
    { role: "user" as const, content: "刚才问的是事件A", timestamp: 1 },
    ...Array.from({ length: 8 }, (_, i) => [
      {
        ...assistant,
        content: [
          {
            type: "toolCall" as const,
            id: "huge_" + i,
            name: "fetch_webpage",
            arguments: { url: "https://example.com/" + "a".repeat(4000) },
          },
        ],
      },
      {
        role: "toolResult" as const,
        toolCallId: "huge_" + i,
        toolName: "fetch_webpage",
        content: [{ type: "text" as const, text: "来源".repeat(5000) }],
        isError: false,
        timestamp: i,
      },
    ]).flat(),
    assistant,
  ];
  const history = trimHistory(group);
  assert.equal(history.length, 2);
  assert.match(JSON.stringify(history), /刚才问的是事件A/);
  assert.match(JSON.stringify(history), /最后确认的讨论对象仍是事件A/);
  assert.ok(!history.some((m) => m.role === "toolResult"));
  assert.ok(Buffer.byteLength(JSON.stringify(history)) <= 12000);
});
