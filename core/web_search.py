"""
core/web_search.py
动态网页搜索模块 - 完整接入 google_auto_delivery 爬虫能力

流程:
  1. Serper 搜索 → 拿到 title/snippet/url
  2. 并行 fetch_url_text → 抓取页面全文
  3. parse_page → 提取正文
  4. DeepSeek summarize_page → 生成 150-250 字中文摘要
  5. 返回结构化结果注入 prompt
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# 加载 .env（模块级，只执行一次）
from core.web_search_app.utils import load_dotenv as _load_dotenv
_load_dotenv(Path(__file__).parent.parent / ".env")
# 把爬虫模块加入路径
_APP_DIR = Path(__file__).parent / "web_search_app"
if str(_APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_APP_DIR.parent))

from core.web_search_app.webfetch import fetch_url_text, parse_page
from core.web_search_app.deepseek import DeepSeekClient
from core.web_search_app.constants import SERPER_SEARCH_URL, DEFAULT_DEEPSEEK_BASE_URL, DEFAULT_DEEPSEEK_MODEL

# ── 超参数 ────────────────────────────────────────────────
MAX_HTML_BYTES    = 2 * 1024 * 1024   # 每页最多抓 2MB
FETCH_TIMEOUT     = 12                 # 页面抓取超时（秒）
SEARCH_TIMEOUT    = 10                 # Serper 搜索超时（秒）
MAX_RESULTS       = 4                  # 搜索返回条数
MAX_FETCH         = 3                  # 最多并行抓几个页面
MAX_PAGE_CHARS    = 6000               # 送给 DeepSeek 的正文上限


def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "GTSNA-WebSearch/1.0"
    return session


def _serper_search(query: str, api_key: str, max_results: int) -> list[dict]:
    """Serper 搜索，返回 list[{title, url, snippet, source}]"""
    session = _get_session()
    try:
        resp = session.post(
            SERPER_SEARCH_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 10, "gl": "us", "hl": "en"},
            timeout=SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        organic = resp.json().get("organic", [])[:max_results]
        return [
            {
                "title":   item.get("title", ""),
                "url":     item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "source":  item.get("displayLink", ""),
            }
            for item in organic
            if item.get("link")
        ]
    except Exception as e:
        print(f"[web_search] Serper 搜索失败: {e}", flush=True)
        return []


def _fetch_and_summarize(
    item: dict,
    *,
    query: str,
    deepseek_client: DeepSeekClient,
    session: requests.Session,
) -> dict:
    """抓取单个页面并生成摘要，失败时降级用 snippet"""
    url     = item["url"]
    title   = item["title"]
    snippet = item["snippet"]

    # 1. 抓页面
    fetch = fetch_url_text(session, url, max_bytes=MAX_HTML_BYTES, timeout=FETCH_TIMEOUT)
    if not fetch.ok or not fetch.text:
        print(f"[web_search] 抓取失败 {url[:60]}: {fetch.error}", flush=True)
        return {**item, "abstract": snippet, "fetch_ok": False}

    # 2. 解析正文
    page = parse_page(fetch.text)
    page_text = page.text[:MAX_PAGE_CHARS]
    if not page_text.strip():
        return {**item, "abstract": snippet, "fetch_ok": True}

    # 3. DeepSeek 生成摘要
    try:
        abstract = deepseek_client.summarize_page(
            search_keyword=query,
            report_context="中国国际贸易战略分析，关注贸易政策、关键矿产、WTO规则、地缘博弈",
            title=title,
            url=url,
            snippet=snippet,
            page_text=page_text,
        )
        print(f"[web_search] 摘要生成成功 {url[:60]}", flush=True)
        return {**item, "abstract": abstract, "fetch_ok": True}
    except Exception as e:
        print(f"[web_search] 摘要生成失败 {url[:60]}: {e}", flush=True)
        # 降级：用页面正文前300字
        fallback = page.meta_description or page_text[:300]
        return {**item, "abstract": fallback, "fetch_ok": True}


def dynamic_web_search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """
    完整网页搜索流程：Serper → fetch → parse → summarize
    返回 list[dict]，每条含 title/url/snippet/abstract/source/_source_type
    无 API Key 时静默返回空列表
    """
    serper_key   = os.environ.get("SERPER_API_KEY", "")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")

    if not serper_key:
        print("[web_search] 未配置 SERPER_API_KEY，跳过", flush=True)
        return []

    # 1. 搜索
    items = _serper_search(query, serper_key, max_results)
    if not items:
        return []
    print(f"[web_search] Serper 返回 {len(items)} 条", flush=True)

    # 2. 并行抓取 + 摘要
    to_fetch = items[:MAX_FETCH]
    session  = _get_session()

    if deepseek_key:
        ds_client = DeepSeekClient(
            api_key  = deepseek_key,
            base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
            model    = os.environ.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
            session  = session,
        )
    else:
        ds_client = None
        print("[web_search] 未配置 DEEPSEEK_API_KEY，将只用页面正文，不生成摘要", flush=True)

    results: list[dict] = []

    def process(item: dict) -> dict:
        if ds_client:
            return _fetch_and_summarize(item, query=query, deepseek_client=ds_client, session=session)
        # 无 DeepSeek 时只抓正文前300字
        fetch = fetch_url_text(session, item["url"], max_bytes=MAX_HTML_BYTES, timeout=FETCH_TIMEOUT)
        if fetch.ok and fetch.text:
            page = parse_page(fetch.text)
            fallback = page.meta_description or page.text[:300]
            return {**item, "abstract": fallback, "fetch_ok": True}
        return {**item, "abstract": item["snippet"], "fetch_ok": False}

    with ThreadPoolExecutor(max_workers=MAX_FETCH) as executor:
        futures = {executor.submit(process, item): item for item in to_fetch}
        for future in as_completed(futures):
            try:
                result = future.result()
                result["_source_type"] = "web_search"
                results.append(result)
            except Exception as e:
                item = futures[future]
                print(f"[web_search] 处理失败 {item['url'][:60]}: {e}", flush=True)
                results.append({**item, "abstract": item["snippet"], "_source_type": "web_search"})

    # 保持原始顺序
    url_order = {item["url"]: i for i, item in enumerate(to_fetch)}
    results.sort(key=lambda r: url_order.get(r["url"], 999))

    print(f"[web_search] 完成，{len(results)} 条带摘要", flush=True)
    return results
