"""One task-wide budget shared by both harnesses and all nested batch-model calls."""
import json
import asyncio
from typing import TypeVar

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, PrivateAttr

from .settings import OpinionSettings

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, settings: OpinionSettings, on_change=None):
        self.settings = settings
        self.calls = self.tokens = self.reserved = self.tool_calls = 0
        self.input_tokens = self.output_tokens = 0
        self.context_mode = False
        self.context_reserved = 0
        self.settled_calls = 0
        self.headroom_tokens = self.headroom_calls = 0
        self.on_change = on_change

    def persist(self):
        if self.on_change:
            self.on_change(self.snapshot())

    def reserve(self, messages, output: int):
        # UTF-8 bytes is deliberately conservative; this is a hard upper-bound admission budget,
        # distinct from actual provider-reported usage. It includes tool definitions below.
        estimate = len(str(messages).encode("utf-8")) + output
        if self.calls >= self.settings.max_model_calls - self.headroom_calls:
            raise BudgetExceeded(f"模型调用预算不足：已调用 {self.calls} 次，上限 {self.settings.max_model_calls} 次，"
                                 f"为最终报告预留 {self.headroom_calls} 次；未发送本次请求。")
        remaining = max(0, self.settings.max_tokens - self.headroom_tokens - self.reserved)
        if estimate > remaining:
            raise BudgetExceeded(f"模型 Token 预算不足：累计已计入 {self.reserved}，总上限 {self.settings.max_tokens}，"
                                 f"为最终报告预留 {self.headroom_tokens}；下一请求保守估算 {estimate}，"
                                 f"当前可用 {remaining}。未发送本次请求；这不表示实际 Token 已全部用完。")
        if self.context_mode:
            if self.context_reserved + estimate > self.settings.context_tokens:
                raise BudgetExceeded("已达到宏观语境的独立 Token 预算，保留已完成的评论分析")
            self.context_reserved += estimate
        self.calls += 1
        self.reserved += estimate
        self.persist()
        return estimate, self.context_mode

    def settle(self, reservation, usage):
        """Release unused headroom only after the provider supplies valid actual usage.

        Failed/cancelled calls and responses without usage retain their full reservation.
        The per-call byte bound and output cap still gate every request before it is sent.
        """
        if not isinstance(usage, dict):
            return
        counts = [usage.get(key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
            return
        incoming, outgoing, total = counts
        if total < incoming + outgoing:
            return
        estimate, in_context = reservation
        self.reserved += total - estimate
        if in_context:
            self.context_reserved += total - estimate
        self.input_tokens += incoming
        self.output_tokens += outgoing
        self.tokens += total
        self.settled_calls += 1
        self.persist()

    def snapshot(self):
        return {"model_calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "budget_version": 2, "settled_model_calls": self.settled_calls,
                "reported_tokens": self.tokens, "reserved_token_upper_bound": self.reserved,
                "context_reserved_token_upper_bound": self.context_reserved,
                "tool_calls": self.tool_calls}


class BudgetChatModel(ChatOpenAI):
    _budget: Budget = PrivateAttr()
    _gate: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        async with self._gate:
            return await self._bounded_generate(messages, stop, run_manager, **kwargs)

    async def _bounded_generate(self, messages, stop=None, run_manager=None, **kwargs):
        reservation = self._budget.reserve([messages, kwargs.get("tools", [])], self._budget.settings.model_output)
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        usage = (result.llm_output or {}).get("token_usage", {})
        self._budget.settle(reservation, usage)
        return result


def make_model(trace, settings: OpinionSettings, budget: Budget):
    extra = {"thinking": {"type": "disabled"}} if "api.deepseek.com" in trace.llm_base_url else {}
    model = BudgetChatModel(model=trace.llm_model, api_key=trace.llm_key, base_url=trace.llm_base_url,
                            max_tokens=settings.model_output, timeout=trace.call_timeout, max_retries=0,
                            extra_body=extra, temperature=0, use_responses_api=False)
    model._budget = budget
    return model


async def structured(model, prompt: str, data: dict, schema: type[T]) -> T:
    response = await model.bind(response_format={"type": "json_object"}).ainvoke([
        SystemMessage(content=prompt + "\n返回 JSON，符合此 Schema：" + json.dumps(schema.model_json_schema(), ensure_ascii=False)),
        HumanMessage(content=json.dumps(data, ensure_ascii=False)),
    ])
    return schema.model_validate_json(response.content)


class ToolPolicy(AgentMiddleware):
    """Hide and deny Deep Agents' generic delegation/filesystem/execution tools.

    The default StateBackend is also memory-only; no host filesystem or shell is mounted.
    Tools remain checked at execution, even if a model invents a hidden tool call.
    """
    def __init__(self, allowed: set[str], budget: Budget):
        self.allowed, self.budget = allowed | {"write_todos"}, budget

    async def awrap_model_call(self, request, handler):
        allowed = [t for t in request.tools if (t.name if hasattr(t, "name") else t.get("name")) in self.allowed]
        return await handler(request.override(tools=allowed))

    async def awrap_tool_call(self, request, handler):
        name = request.tool_call["name"]
        if name not in self.allowed:
            return ToolMessage(content="此任务未授权该工具", tool_call_id=request.tool_call["id"])
        self.budget.tool_calls += 1
        self.budget.persist()
        if self.budget.tool_calls > 100:
            raise BudgetExceeded("已达到工具调用预算")
        return await handler(request)
