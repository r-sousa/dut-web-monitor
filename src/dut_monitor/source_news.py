from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .source_newsletters import MONTHS
from .util import canonicalise_url, hash_payload, normalise_space, read_json, stable_external_id

KNOWN_TOPICS = {
    "business models & tools", "circular economy", "culture & values", "energy in urban planning",
    "energy markets", "governance & policy", "integrated energy systems", "public space & proximity",
    "sustainable mobility", "technology & infrastructure", "transport of goods", "urban greening",
    "urban metabolism", "urban regeneration",
}
KNOWN_PATHWAYS = {"15-minute city", "circular urban economies", "positive energy districts"}


def _news_period(text: str) -> tuple[int | None, int | None, str | None]:
    month_pattern = "|".join(sorted((re.escape(k) for k in MONTHS), key=len, reverse=True))
    match = re.search(rf"\b({month_pattern})\s+(20\d{{2}})\b", text, flags=re.I)
    if not match:
        return None, None, None
    month = MONTHS[match.group(1).casefold()]
    year = int(match.group(2))
    return year, month, f"{year:04d}-{month:02d}-01"


def parse_news(html: str, fetched_url: str, retrieved_at: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    canonical = soup.select_one('link[rel="canonical"][href]')
    canonical_url = canonicalise_url(fetched_url, canonical["href"] if canonical else fetched_url)
    h1 = soup.find("h1")
    if not h1:
        raise ValueError("News page has no h1 title")
    title = normalise_space(h1.get_text(" ", strip=True)) or "Untitled"
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = normalise_space(root.get_text(" ", strip=True)) or ""
    news_type_match = re.search(r"\b(News|Story)\b", text[:800], flags=re.I)
    news_type = news_type_match.group(1).title() if news_type_match else "Unknown"
    year, month, published_sort_date = _news_period(text[:1200])
    author_match = re.search(r"\bBy\s+([^\n|]{2,120}?)(?=\s+(?:Image|Page content|Highlights|The Driving)|$)", text[:1800], flags=re.I)
    author = normalise_space(author_match.group(1)) if author_match else None
    meta = soup.select_one('meta[name="description"][content]')
    description = normalise_space(meta.get("content")) if meta else None
    topics: list[str] = []
    pathways: list[str] = []
    for anchor in root.select("a[href]"):
        label = normalise_space(anchor.get_text(" ", strip=True))
        if not label:
            continue
        lowered = label.casefold().strip(" \u202f")
        if lowered in KNOWN_TOPICS and label not in topics:
            topics.append(label)
        if lowered in KNOWN_PATHWAYS and label not in pathways:
            pathways.append(label)
    payload = {"title": title, "news_type": news_type, "published_sort_date": published_sort_date, "author": author, "topics": topics, "pathways": pathways, "canonical_url": canonical_url}
    return {
        "external_id": stable_external_id("news", canonical_url),
        "content_type": "news",
        "title": title,
        "canonical_url": canonical_url,
        "news_type": news_type,
        "published_year": year,
        "published_month": month,
        "published_sort_date": published_sort_date,
        "author": author,
        "topics_json": json.dumps(topics, ensure_ascii=False),
        "transition_pathways_json": json.dumps(pathways, ensure_ascii=False),
        "source_description": description,
        "source_priority": 1,
        "source_role": "primary_european",
        "source_name": "DUT Partnership",
        "source_status": "active",
        "retrieved_at": retrieved_at,
        "content_hash": hash_payload(payload),
    }


def load_manual_news(path: Path, retrieved_at: str) -> list[dict[str, Any]]:
    records = []
    for item in read_json(path, []):
        title = normalise_space(str(item.get("title") or ""))
        raw_url = str(item.get("canonical_url") or "").strip()
        if not title or not raw_url:
            continue
        url = canonicalise_url("https://www.ccdr-n.pt", raw_url)
        copy = dict(item)
        copy.update({"external_id": stable_external_id("news", url), "content_type": "news", "title": title, "canonical_url": url, "source_priority": 2, "source_role": "secondary_manual", "source_name": "CCDR NORTE manual update", "source_status": "active", "retrieved_at": retrieved_at})
        copy["content_hash"] = hash_payload({key: value for key, value in copy.items() if key not in {"retrieved_at", "content_hash"}})
        records.append(copy)
    return records


def merge_news(primary: list[dict[str, Any]], manual: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for item in [*manual, *primary]:
        key = item["canonical_url"]
        current = by_url.get(key)
        if current is None or item.get("source_priority", 99) <= current.get("source_priority", 99):
            by_url[key] = item
    return sorted(by_url.values(), key=lambda item: (item.get("published_sort_date") or "0000-00-00", item["title"]), reverse=True)
