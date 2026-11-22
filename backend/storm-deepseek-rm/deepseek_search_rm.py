"""E2 自定义检索模块：DeepSeekSearchRM（knowledge-storm / Co-STORM 用）。

契约（knowledge_storm/rm.py 官方 YouRM/TavilySearchRM 同款）：
- 继承 dspy.Retrieve，__init__ 调 super().__init__(k=k)
- forward(query_or_queries, exclude_urls=[]) -> [{"url","title","description","snippets":[...]}]
- get_usage_and_reset() -> {"DeepSeekSearchRM": 查询次数}
- 出错记日志不抛异常，避免中断圆桌/文章流程

与 E1 插件同套逻辑：POST /v1/tools/search，need_content=true 直接带正文，
免本地抓页；正文缺失回退 summary；query 截断 128 字符；408/429/5xx 重试一次。
"""

import logging
import os
import time
from typing import Callable, List, Union

import dspy
import requests

_ENDPOINT = "https://api.deepseek.com/v1/tools/search"


class DeepSeekSearchRM(dspy.Retrieve):
    def __init__(self, deepseek_api_key=None, k=3, is_valid_source: Callable = None):
        super().__init__(k=k)
        self.api_key = deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            logging.warning("DeepSeekSearchRM: 未设置 DEEPSEEK_API_KEY，检索将返回空结果。")
        self.is_valid_source = is_valid_source or (lambda url: True)
        self.usage = 0

    def get_usage_and_reset(self):
        usage = self.usage
        self.usage = 0
        return {"DeepSeekSearchRM": usage}

    def _search_one(self, query: str) -> list:
        payload = {
            "query": query.strip()[:128],
            "count": max(1, min(self.k, 50)),
            "need_content": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(2):
            try:
                resp = requests.post(_ENDPOINT, headers=headers, json=payload, timeout=30)
                if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(2)
                    continue
                resp.raise_for_status()
                return resp.json().get("results", [])
            except (requests.RequestException, ValueError) as e:
                if attempt == 0:
                    time.sleep(2)
                    continue
                logging.error(f"DeepSeekSearchRM 检索失败 query={query}: {e}")
        return []

    def forward(self, query_or_queries: Union[str, List[str]], exclude_urls: List[str] = []):
        queries = [query_or_queries] if isinstance(query_or_queries, str) else query_or_queries
        self.usage += len(queries)
        collected = []
        if not self.api_key:
            return collected
        for query in queries:
            for r in self._search_one(query):
                url = r.get("url")
                text = r.get("content") or r.get("summary") or r.get("snippet") or ""
                if not url or not text:
                    continue
                if url in exclude_urls or not self.is_valid_source(url):
                    continue
                collected.append({
                    "url": url,
                    "title": r.get("title", ""),
                    "description": r.get("snippet", "") or r.get("summary", "")[:200],
                    "snippets": [text],
                })
        return collected
