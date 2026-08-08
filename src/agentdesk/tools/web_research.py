"""网页调研能力：搜索（Tavily + 免 key fallback）、网页抓取与正文提取、多轮调研。

- SearchProvider 抽象：Tavily API 为主；无 key 时自动回退 DuckDuckGo/Bing HTML 解析。
- fetch_page：抓取网页并提取正文（去除导航/脚本，截断）。
- research_topic：搜索 → 抓取关键页面 → 汇总带引用的资料（生成交给 Agent 完成）。
- build_web_tools：把以上能力注册为 Agent 工具（web_search / fetch_page / research_report）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from agentdesk.config import Settings
from agentdesk.tools.registry import Tool, ToolContext, ToolResult

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

TAVILY_URL = "https://api.tavily.com/search"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    truncated: bool


@dataclass
class ResearchReport:
    topic: str
    sources: list[dict]
    fetched: int
    truncated_pages: int


class SearchProvider:
    """搜索 provider 抽象。"""

    name = "base"

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        raise NotImplementedError


class TavilyProvider(SearchProvider):
    """Tavily 搜索 API（免费额度，专为 agent 设计）。"""

    name = "tavily"

    def __init__(
        self,
        api_key: str,
        max_results: int = 8,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.max_results = max_results
        self.timeout = timeout
        self._client = client

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results or self.max_results,
            "search_depth": "basic",
        }
        if self._client is not None:
            resp = self._client.post(TAVILY_URL, json=payload, timeout=self.timeout)
        else:
            resp = httpx.post(TAVILY_URL, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        out: list[SearchResult] = []
        for r in data.get("results", []):
            snippet = (r.get("content") or r.get("snippet") or "")[:300]
            out.append(
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=snippet,
                )
            )
        return out


def _ddg_target_url(href: str) -> str:
    """DuckDuckGo 结果是重定向链接，提取真实目标 URL。"""
    if "uddg=" not in href:
        return href
    qs = parse_qs(urlparse(href).query)
    return qs["uddg"][0] if "uddg" in qs else href


class FallbackProvider(SearchProvider):
    """免 key 搜索：DuckDuckGo HTML 或 Bing，稳定性较弱。"""

    name = "fallback"

    def __init__(
        self,
        engine: str = "duckduckgo",
        max_results: int = 8,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.engine = engine
        self.max_results = max_results
        self.timeout = timeout
        self._client = client

    def _get(self, url: str, params: dict) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, params=params, timeout=self.timeout)
        return httpx.get(url, params=params, headers={"User-Agent": UA}, timeout=self.timeout)

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        n = max_results or self.max_results
        if self.engine == "bing":
            return self._bing(query, n)
        return self._duckduckgo(query, n)

    def _duckduckgo(self, query: str, n: int) -> list[SearchResult]:
        resp = self._get("https://html.duckduckgo.com/html/", {"q": query})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        out: list[SearchResult] = []
        for link in soup.select(".result__a")[:n]:
            title = link.get_text(strip=True)
            snippet_el = link.find_next(class_="result__snippet")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            out.append(
                SearchResult(
                    title=title,
                    url=_ddg_target_url(str(link.get("href", ""))),
                    snippet=snippet[:300],
                )
            )
        return out

    def _bing(self, query: str, n: int) -> list[SearchResult]:
        resp = self._get("https://www.bing.com/search", {"q": query})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        out: list[SearchResult] = []
        for li in soup.select("li.b_algo")[:n]:
            a = li.select_one("h2 a")
            if a is None:
                continue
            p = li.select_one(".b_caption p") or li.select_one("p")
            out.append(
                SearchResult(
                    title=a.get_text(strip=True),
                    url=str(a.get("href", "")),
                    snippet=(p.get_text(strip=True) if p else "")[:300],
                )
            )
        return out


def get_search_provider(settings: Settings) -> SearchProvider:
    """按配置选择搜索 provider；Tavily 缺 key 时自动回退 fallback。"""
    cfg = settings.search
    if cfg.provider == "tavily":
        key = os.getenv(cfg.tavily.api_key_env, "")
        if key:
            return TavilyProvider(key, cfg.tavily.max_results)
    return FallbackProvider(cfg.fallback.engine, cfg.fallback.max_results)


def fetch_page(
    url: str,
    *,
    timeout: float = 15.0,
    max_chars: int = 6000,
    client: httpx.Client | None = None,
) -> PageContent:
    """抓取网页并提取正文（去除脚本/导航，截断）。失败抛 httpx 异常。"""
    if client is not None:
        resp = client.get(url, timeout=timeout, follow_redirects=True)
    else:
        resp = httpx.get(
            url,
            headers={"User-Agent": UA},
            timeout=timeout,
            follow_redirects=True,
        )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    parts: list[str] = []
    for el in main.find_all(["p", "h1", "h2", "h3", "li"]):
        text = el.get_text(" ", strip=True)
        if text:
            parts.append(text)
    body = "\n".join(parts)
    truncated = len(body) > max_chars
    return PageContent(url=url, title=title, text=body[:max_chars], truncated=truncated)


def research_topic(
    topic: str,
    provider: SearchProvider,
    *,
    max_pages: int = 5,
    max_chars_per_page: int = 6000,
    timeout: float = 15.0,
    client: httpx.Client | None = None,
) -> ResearchReport:
    """多轮调研：搜索 → 抓取关键页面 → 汇总带来源的资料。

    报告文本由 Agent 基于 sources 生成（引用可溯源到 url）。
    """
    results = provider.search(topic, max_results=max_pages)
    sources: list[dict] = []
    fetched = 0
    for r in results[:max_pages]:
        content = ""
        try:
            page = fetch_page(
                r.url,
                timeout=timeout,
                max_chars=max_chars_per_page,
                client=client,
            )
            content = page.text
            fetched += 1
        except httpx.HTTPError:
            content = ""
        sources.append(
            {"url": r.url, "title": r.title, "snippet": r.snippet, "content": content}
        )
    truncated_pages = sum(1 for s in sources if len(s["content"]) >= max_chars_per_page)
    return ResearchReport(
        topic=topic,
        sources=sources,
        fetched=fetched,
        truncated_pages=truncated_pages,
    )


# ---------- Agent 工具包装 ----------


class WebSearchParams(BaseModel):
    query: str = Field(description="搜索关键词")
    max_results: int = Field(default=5, ge=1, le=10)


def _web_search(args: dict, ctx: ToolContext) -> ToolResult:
    provider = get_search_provider(ctx.settings)
    try:
        results = provider.search(args["query"], args["max_results"])
    except httpx.HTTPError as e:
        return ToolResult(summary=f"搜索失败: {e}")
    if not results:
        return ToolResult(summary="没有搜索到结果")
    items = [
        {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
    ]
    return ToolResult(
        summary=f"搜索「{args['query']}」得到 {len(items)} 条结果",
        data={"query": args["query"], "results": items},
    )


class FetchPageParams(BaseModel):
    url: str = Field(description="网页 URL")


def _fetch_page(args: dict, ctx: ToolContext) -> ToolResult:
    cfg = ctx.settings.tools.web_research
    try:
        page = fetch_page(
            args["url"],
            timeout=cfg.request_timeout_seconds,
            max_chars=cfg.max_chars_per_page,
        )
    except httpx.HTTPError as e:
        return ToolResult(summary=f"抓取失败: {e}")
    return ToolResult(
        summary=f"已抓取「{page.title[:80] or args['url']}」（{len(page.text)} 字符）",
        data={
            "url": page.url,
            "title": page.title,
            "text": page.text,
            "truncated": page.truncated,
        },
    )


class ResearchParams(BaseModel):
    topic: str = Field(description="调研主题")
    max_pages: int = Field(default=5, ge=1, le=10)


def _research(args: dict, ctx: ToolContext) -> ToolResult:
    cfg = ctx.settings.tools.web_research
    provider = get_search_provider(ctx.settings)
    report = research_topic(
        args["topic"],
        provider,
        max_pages=args["max_pages"],
        max_chars_per_page=cfg.max_chars_per_page,
        timeout=cfg.request_timeout_seconds,
    )
    return ToolResult(
        summary=f"调研「{args['topic']}」：抓取 {report.fetched}/{len(report.sources)} 个页面",
        data={"topic": report.topic, "sources": report.sources},
    )


def build_web_tools() -> list[Tool]:
    """网页调研工具集（只读，无需确认）。"""
    return [
        Tool(
            name="web_search",
            description="搜索网页，返回标题/链接/摘要",
            parameters=WebSearchParams,
            func=_web_search,
        ),
        Tool(
            name="fetch_page",
            description="抓取单个网页并提取正文（截断）",
            parameters=FetchPageParams,
            func=_fetch_page,
        ),
        Tool(
            name="research_report",
            description=(
                "对主题做多轮调研：搜索并抓取多个关键页面，"
                "返回带来源（url）的资料汇总，供撰写带引用的调研笔记"
            ),
            parameters=ResearchParams,
            func=_research,
        ),
    ]
