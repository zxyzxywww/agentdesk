"""LLM 客户端封装：OpenAI 兼容对话、token/成本统计、模型切换。

- API key 从环境变量读取（.env，见 config.py），不硬编码。
- 成本按模型价格表估算（元/百万 tokens），价格表可自行调整。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, cast

from openai import OpenAI

from agentdesk.config import Settings, get_settings

# 模型价格表（元 / 百万 tokens）：(输入价, 输出价)，按各平台公开定价近似
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-flash": (1.0, 2.0),  # 当前默认模型（DeepSeek 官方 V4-Flash 定价近似）
    "deepseek-v4-flash": (1.0, 2.0),  # 同上（完整别名）
    "deepseek-chat": (2.0, 3.0),
    "deepseek-reasoner": (4.0, 16.0),
    # 火山方舟 deepseek-v4-flash-ga-260731：计价以方舟控制台账单为准，先用默认价近似
    "deepseek-v4-flash-ga-260731": (2.0, 3.0),
}
DEFAULT_PRICE: tuple[float, float] = (1.0, 2.0)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按价格表估算一次调用成本（元）。未知模型用默认价。"""
    price_in, price_out = MODEL_PRICES.get(model, DEFAULT_PRICE)
    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000


@dataclass
class UsageStats:
    """进程内累计的调用统计。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_yuan: float = 0.0
    last_call_duration_s: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: UsageStats) -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cost_yuan += other.cost_yuan
        self.last_call_duration_s = other.last_call_duration_s


@dataclass
class ChatResult:
    """一次 chat 调用的结果。tool_calls 为简单 dict 结构（id/name/arguments）。"""

    content: str | None
    tool_calls: list[dict[str, str]]
    prompt_tokens: int
    completion_tokens: int
    model: str


class LLMClient:
    """OpenAI 兼容聊天客户端。client 懒加载：无 key 时首次调用才报错。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.stats = UsageStats()
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            key = os.getenv(self.settings.model.api_key_env, "")
            if not key:
                raise RuntimeError(
                    f"缺少 API key：请在项目根 .env 中设置 {self.settings.model.api_key_env}"
                )
            self._client = OpenAI(api_key=key, base_url=self.settings.model.base_url)
        return self._client

    def reset_client(self) -> None:
        """模型/地址/密钥切换后重建底层客户端。"""
        self._client = None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """发送一轮对话，返回助手消息（含工具调用）与用量增量。"""
        chosen = model or self.settings.model.chat_model
        t0 = time.perf_counter()
        # 对外保留简单 dict 结构；SDK 类型严格，此处显式放宽
        resp = self.client.chat.completions.create(
            model=chosen,
            messages=cast(Any, messages),
            tools=cast(Any, tools),
            temperature=(
                temperature if temperature is not None else self.settings.model.temperature
            ),
            max_tokens=self.settings.model.max_tokens,
        )
        self.stats.last_call_duration_s = time.perf_counter() - t0

        msg = resp.choices[0].message
        content = msg.content
        tool_calls: list[dict[str, str]] = []
        for tc in msg.tool_calls or []:
            fn = getattr(tc, "function", None)
            if fn is not None:
                tool_calls.append(
                    {
                        "id": getattr(tc, "id", ""),
                        "name": fn.name,
                        "arguments": fn.arguments,
                    }
                )

        usage = resp.usage
        prompt_tokens = int(usage.prompt_tokens) if usage else 0
        completion_tokens = int(usage.completion_tokens) if usage else 0

        self.stats.calls += 1
        self.stats.prompt_tokens += prompt_tokens
        self.stats.completion_tokens += completion_tokens
        self.stats.cost_yuan += estimate_cost(chosen, prompt_tokens, completion_tokens)

        return ChatResult(
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=chosen,
        )
