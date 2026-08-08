"""网页调研测试：搜索 provider（Tavily/DDG/Bing）、抓取、调研流程、工具注册（全离线 Mock）。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agentdesk.config import load_settings
from agentdesk.tools.registry import ToolContext, ToolRegistry
from agentdesk.tools.web_research import (
    FallbackProvider,
    TavilyProvider,
    fetch_page,
    get_search_provider,
    research_topic,
)

DDG_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1&rut=abc">
    Example Page 1
  </a>
  <a class="result__snippet">这是第一条摘要</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.org/page2">Example Page 2</a>
  <a class="result__snippet">第二条摘要</a>
</div>
</body></html>
"""

BING_HTML = """
<html><body>
<li class="b_algo">
  <h2><a href="https://bing.example.com/a">Bing Result A</a></h2>
  <div class="b_caption"><p>Bing 摘要 A</p></div>
</li>
<li class="b_algo">
  <h2><a href="https://bing.example.com/b">Bing Result B</a></h2>
  <div class="b_caption"><p>Bing 摘要 B</p></div>
</li>
</body></html>
"""

ARTICLE_HTML = """
<html><head><title>测试文章</title></head><body>
<nav><a href="#">导航</a></nav>
<main>
  <h1>标题</h1>
  <p>第一段正文。</p>
  <p>第二段正文。</p>
  <script>var x = 1;</script>
</main>
<footer>页脚</footer>
</body></html>
"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tavily_provider_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "T1", "url": "https://t.example/1", "content": "内容一"},
                    {"title": "T2", "url": "https://t.example/2"},
                ]
            },
        )

    p = TavilyProvider("fake-key", client=_client(handler))
    results = p.search("python agent", max_results=5)
    assert len(results) == 2
    assert results[0].title == "T1"
    assert results[0].url == "https://t.example/1"
    assert "内容一" in results[0].snippet


def test_duckduckgo_provider_parses_and_decodes_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "duckduckgo.com" in request.url.host
        return httpx.Response(200, text=DDG_HTML)

    p = FallbackProvider(engine="duckduckgo", client=_client(handler))
    results = p.search("query", max_results=3)
    assert len(results) == 2
    assert results[0].title == "Example Page 1"
    assert results[0].url == "https://example.com/page1"  # uddg 解码
    assert results[1].url == "https://example.org/page2"


def test_bing_provider_parses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "bing.com" in request.url.host
        return httpx.Response(200, text=BING_HTML)

    p = FallbackProvider(engine="bing", client=_client(handler))
    results = p.search("query")
    assert [r.title for r in results] == ["Bing Result A", "Bing Result B"]
    assert results[0].snippet == "Bing 摘要 A"


def test_get_search_provider_fallback_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    settings = load_settings()
    settings.search.provider = "tavily"
    provider = get_search_provider(settings)
    assert isinstance(provider, FallbackProvider)


def test_get_search_provider_tavily_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    settings = load_settings()
    settings.search.provider = "tavily"
    provider = get_search_provider(settings)
    assert isinstance(provider, TavilyProvider)


def test_fetch_page_extracts_article() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=ARTICLE_HTML)

    page = fetch_page("https://example.com/article", client=_client(handler))
    assert page.title == "测试文章"
    assert "第一段正文" in page.text
    assert "第二段正文" in page.text
    assert "导航" not in page.text  # nav 被移除
    assert "var x" not in page.text  # script 被移除
    assert "页脚" not in page.text  # footer 被移除
    assert not page.truncated


def test_fetch_page_truncates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><p>" + "x" * 500 + "</p></body></html>",
        )

    page = fetch_page("https://example.com/long", max_chars=100, client=_client(handler))
    assert page.truncated
    assert len(page.text) <= 100


def test_research_topic_collects_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "duckduckgo" in request.url.host:
            return httpx.Response(200, text=DDG_HTML)
        return httpx.Response(200, text=ARTICLE_HTML)

    provider = FallbackProvider(engine="duckduckgo", client=_client(handler))
    report = research_topic(
        "LLM agent",
        provider,
        max_pages=2,
        max_chars_per_page=1000,
        client=_client(handler),
    )
    assert report.topic == "LLM agent"
    assert len(report.sources) == 2
    assert report.fetched == 2
    assert report.sources[0]["url"] == "https://example.com/page1"
    assert "正文" in report.sources[0]["content"]


def test_web_tools_registered_and_executable(tmp_path: Path) -> None:
    reg = ToolRegistry(
        [
            *__import__("agentdesk.tools", fromlist=["build_default_tools"]).build_default_tools()
        ]
    )
    assert {"web_search", "fetch_page", "research_report"} <= set(reg.names())

    settings = load_settings()
    settings.search.provider = "fallback"
    ctx = ToolContext(workspace_root=tmp_path, settings=settings)
    # 不联网：直接验证参数校验（缺 query 报错）
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        reg.execute("web_search", {}, ctx)
