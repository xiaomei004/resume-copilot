"""检索能力抽象。

设计要点：**没有 key 不是错误**。流水线会在检索不可用时自动降级，
把"未启用检索"写进结果，而不是让整个任务失败。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchHit:
    title: str
    url: str
    content: str

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "content": self.content}


class SearchProvider(Protocol):
    name: str
    enabled: bool

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


class NoopProvider:
    name = "none"
    enabled = False

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return []


class TavilyProvider:
    """Tavily 搜索 API（https://tavily.com）。"""

    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout: int = 30):
        self.api_key = api_key
        self.timeout = timeout
        self.enabled = bool(api_key)

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self.enabled:
            return []
        payload = json.dumps(
            {"api_key": self.api_key, "query": query, "max_results": max_results, "search_depth": "basic"},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            return []
        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            hits.append(
                SearchHit(
                    title=str(item.get("title", ""))[:120],
                    url=str(item.get("url", "")),
                    content=str(item.get("content", ""))[:1200],
                )
            )
        return hits


def get_provider(api_key: str, enabled: bool = True) -> SearchProvider:
    if enabled and api_key:
        return TavilyProvider(api_key)
    return NoopProvider()


def build_queries(jd: dict, extra: list[str] | None = None) -> list[str]:
    """从岗位画像里拼出 3 条检索式：面经、公司动向、岗位要求。"""
    title = jd.get("title") or ""
    company = jd.get("company") or ""
    queries = [
        f"{company} {title} 面经 面试流程 2026",
        f"{company} {title} 校园招聘 要求 2026",
        f"{title} 应届生 简历 怎么写 {' '.join((jd.get('keywords') or [])[:3])}".strip(),
    ]
    for q in extra or []:
        if q and q not in queries:
            queries.append(q)
    return [q.strip() for q in queries if q.strip()][:4]


def collect(provider: SearchProvider, queries: list[str], per_query: int = 4) -> tuple[str, list[dict]]:
    """跑完所有检索式，返回（给模型看的文本, 结构化命中）。"""
    if not provider.enabled:
        return "", []
    blocks: list[str] = []
    stored: list[dict] = []
    for query in queries:
        hits = provider.search(query, max_results=per_query)
        if not hits:
            continue
        blocks.append(f"## 检索式：{query}")
        for hit in hits:
            blocks.append(f"- {hit.title}\n  {hit.url}\n  {hit.content}")
            stored.append({"query": query, **hit.as_dict()})
    text = "\n".join(blocks)[:16000]
    return text, stored
