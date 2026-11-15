import type { AgentRequest } from "@/types/agent";

const analysis = {
  timeline: [
    "起点 · 找到事件首次公开的原始材料，记录发布日期和来源。",
    "转折 · 对照后续报道，标记关键进展、回应和版本变化。",
    "现状 · 把已确认进展和仍待查证的说法分别列出。",
  ],
  context: [
    "发起方 · 查阅原始发布方，明确它在事件中承担的职责。",
    "参与方 · 梳理相关组织与受影响群体，核对各方的公开表态。",
    "背景 · 补充事件发生前的时间、环境和相关规则。",
  ],
  perspectives: [
    "分歧 · 提取不同观点各自在回答的核心问题。",
    "论据 · 对照双方引用的材料，标出可以独立核对的信息。",
    "待查 · 记录证据缺口，以及能改变判断的关键事实。",
  ],
  general: [
    "先确定事件范围，收集原始报道、公开声明及对应日期。",
    "按时间整理重要进展，同时记录相关参与方的公开回应。",
    "将不同观点与其依据配对，标记尚缺来源的说法。",
  ],
};

export function mockReply(request: AgentRequest): string[] {
  const previous = request.history.findLast((message) => message.role === "user");
  const topic = request.topic ?? previous?.topic;
  const intro = topic
    ? `围绕「${topic.title}」，针对你的问题「${request.question}」，可以按下面的步骤推进分析。`
    : previous
      ? `关于追问「${request.question}」，可以结合前面的讨论补充这些材料。`
      : `围绕「${request.question}」，可以从这几个方向展开。`;

  return [
    intro + "\n\n",
    ...(analysis[request.skill ?? "general"].map((line, index) => `${index + 1}. ${line}\n`)),
    "\n以上为模拟分析提纲。提供报道链接、日期或相关声明后，可以继续整理具体材料。",
  ];
}
