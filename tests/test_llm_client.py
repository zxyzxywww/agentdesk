"""LLM 客户端测试（全离线 mock，不依赖真实 API）。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agentdesk.config import load_settings
from agentdesk.llm.client import (
    LLMClient,
    estimate_cost,
)


def _fake_response(content: str | None, tool_calls: list[dict] | None = None) -> SimpleNamespace:
    """构造 openai SDK 风格的响应对象。"""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


def _make_client(monkeypatch: pytest.MonkeyPatch) -> LLMClient:
    settings = load_settings()
    client = LLMClient(settings)

    def fake_create(**kwargs: Any) -> SimpleNamespace:
        tool_calls = None
        if kwargs.get("tools"):
            tool_calls = [
                SimpleNamespace(
                    id="call_1",
                    function=SimpleNamespace(name="list_files", arguments='{"path": "."}'),
                )
            ]
        return _fake_response("已列出文件", tool_calls)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
    monkeypatch.setattr(client, "_client", fake)
    return client


def test_estimate_cost_known_model() -> None:
    # deepseek-chat: 1000 prompt * 2/1e6 + 500 completion * 3/1e6
    assert estimate_cost("deepseek-chat", 1000, 500) == pytest.approx(0.0035)
    assert estimate_cost("deepseek-flash", 1000, 500) == pytest.approx(0.002)


def test_estimate_cost_unknown_model_uses_default() -> None:
    # 默认价已变为 (1.0, 2.0)
    assert estimate_cost("some-new-model", 1000, 500) == pytest.approx(0.002)


def test_chat_returns_content_and_updates_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    result = client.chat(messages=[{"role": "user", "content": "hi"}])
    assert result.content == "已列出文件"
    assert result.model == client.settings.model.chat_model
    assert client.stats.calls == 1
    assert client.stats.prompt_tokens == 100
    assert client.stats.completion_tokens == 50
    assert client.stats.total_tokens == 150
    assert client.stats.cost_yuan == pytest.approx(
        estimate_cost(result.model, 100, 50)
    )


def test_chat_parses_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(monkeypatch)
    result = client.chat(
        messages=[{"role": "user", "content": "列出文件"}],
        tools=[{"type": "function", "function": {"name": "list_files"}}],
    )
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "list_files"
    assert result.tool_calls[0]["arguments"] == '{"path": "."}'


def test_client_lazy_key_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 key 时仅在首次真实调用报错（懒加载）。"""
    settings = load_settings()
    monkeypatch.delenv(settings.model.api_key_env, raising=False)
    client = LLMClient(settings)
    with pytest.raises(RuntimeError, match=settings.model.api_key_env):
        _ = client.client  # 触发懒加载


def test_model_override() -> None:
    settings = load_settings()
    client = LLMClient(settings)
    assert client.settings.model.chat_model == settings.model.chat_model
    # 切换模型 = 换 settings 或传 model 参数；此处验证 settings 读取
    s2 = settings.model_copy(deep=True)
    s2.model.chat_model = "deepseek-reasoner"
    client2 = LLMClient(s2)
    assert client2.settings.model.chat_model == "deepseek-reasoner"
