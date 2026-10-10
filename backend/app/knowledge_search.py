import json
import os
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .llm import LLMError


SEARCH_TOOL = {
    "type": "function",
    "name": "search_experiment_knowledge",
    "description": (
        "Search public knowledge when a fact missing from the CSV and user description is necessary "
        "to understand the experiment, such as dataset split size, metric definition, unit, benchmark "
        "protocol, or method identity. Do not call for facts directly derivable from the supplied data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A focused search query containing the entity, missing fact, and relevant split/version.",
            },
            "reason": {
                "type": "string",
                "description": "Why this fact is necessary for the current experiment interpretation.",
            },
        },
        "required": ["query", "reason"],
        "additionalProperties": False,
    },
}


def _custom_search(query: str) -> list[dict[str, Any]] | None:
    endpoint = os.getenv("EXPERIMENT_SEARCH_API_URL")
    if not endpoint:
        return None
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"query": query, "limit": 5}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "ResearchViz-AI/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    results = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        raise LLMError("自定义搜索接口必须返回 results 数组")
    return [item for item in results[:5] if isinstance(item, dict)]


def _wikipedia_search(query: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": 5,
            "prop": "extracts|info",
            "exintro": 1,
            "explaintext": 1,
            "exchars": 1200,
            "inprop": "url",
            "format": "json",
            "formatversion": 2,
            "utf8": 1,
        }
    )
    request = urllib.request.Request(
        f"https://en.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent": "ResearchViz-AI/1.0 (experiment understanding tool)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    pages = payload.get("query", {}).get("pages", [])
    return [
        {
            "title": page.get("title", "Untitled"),
            "url": page.get("fullurl"),
            "snippet": page.get("extract", "")[:1200],
            "source_type": "public_encyclopedia",
        }
        for page in pages
        if page.get("extract")
    ]


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, Any]] = []
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "a" and "result-link" in classes:
            raw_url = values.get("href") or ""
            if raw_url.startswith("//"):
                raw_url = "https:" + raw_url
            parsed = urllib.parse.urlparse(raw_url)
            target = urllib.parse.parse_qs(parsed.query).get("uddg", [raw_url])[0]
            self.results.append({"title": "", "url": target, "snippet": "", "source_type": "web_search"})
            self._capture = "title"
            self._buffer = []
        elif tag == "td" and "result-snippet" in classes and self.results:
            self._capture = "snippet"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a":
            self.results[-1]["title"] = " ".join("".join(self._buffer).split())
            self._capture = None
        elif self._capture == "snippet" and tag == "td":
            self.results[-1]["snippet"] = " ".join("".join(self._buffer).split())[:1200]
            self._capture = None


def _web_search(query: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://lite.duckduckgo.com/lite/?{params}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; ResearchViz-AI/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", "replace")
    parser = _DuckDuckGoParser()
    parser.feed(body)
    return [item for item in parser.results[:5] if item["title"] and item["url"]]


def search_experiment_knowledge(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    reason = str(arguments.get("reason", "")).strip()
    if len(query) < 3:
        raise LLMError("搜索 query 不能为空")
    try:
        results = _custom_search(query)
        backend = "custom" if results is not None else "duckduckgo_lite"
        if results is None:
            results = _web_search(query)
        if not results:
            backend = "wikipedia"
            results = _wikipedia_search(query)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMError(f"实验知识搜索失败: {type(exc).__name__}") from exc
    return {
        "query": query,
        "reason": reason,
        "backend": backend,
        "results": results,
    }
