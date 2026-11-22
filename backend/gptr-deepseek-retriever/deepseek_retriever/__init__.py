"""GPT Researcher retriever 插件：DeepSeek Search API。

契约（官方 retriever-plugins 文档）：
- __init__(query, query_domains=None)
- search(max_results) -> [{"href": url, "body": snippet, ...}]
- requires_scraping=False 时结果须自带 raw_content（正文）
- 网络/解析错误返回 []，不抛异常

设计取舍：
- need_content=True 让 Search 直接带回网页正文（同价，按成功请求计费），
  免本地抓页、免额外 Fetch 费用。
- 个别结果正文缺失时回退 summary（600–800 字长摘要）作 raw_content，
  保证 requires_scraping=False 契约下每条都有可读文本。
- 408/429/5xx 按官方建议等待后重试一次；402（余额不足）等 4xx 不重试。
"""

import os
import time

import requests
from gpt_researcher.retrievers.base import BaseRetriever

_ENDPOINT = "https://api.deepseek.com/v1/tools/search"


class DeepSeekSearch(BaseRetriever):
    requires_scraping = False

    def __init__(self, query, query_domains=None):
        self.query = query
        self.query_domains = query_domains or []
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")

    def _build_query(self):
        q = self.query.strip()
        if self.query_domains:
            sites = " OR ".join(f"site:{d}" for d in self.query_domains)
            q = f"{q} {sites}"
        return q[:128]  # API 上限 128 个 Unicode 字符

    def search(self, max_results=7):
        if not self.api_key:
            return []
        payload = {
            "query": self._build_query(),
            "count": max(1, min(int(max_results), 50)),
            "need_content": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        items = []
        for attempt in range(2):  # 官方：408/429/5xx 等待后重试
            try:
                resp = requests.post(_ENDPOINT, headers=headers, json=payload, timeout=30)
                if resp.status_code in (408, 429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(2)
                    continue
                resp.raise_for_status()
                items = resp.json().get("results", [])
                break
            except (requests.RequestException, ValueError):
                if attempt == 0:
                    time.sleep(2)
                    continue
                return []
        results = []
        for it in items:
            url = it.get("url")
            raw = it.get("content") or it.get("summary") or it.get("snippet") or ""
            if not url or not raw:
                continue
            results.append({
                "href": url,
                "body": it.get("snippet", ""),
                "raw_content": raw,
            })
        return results
