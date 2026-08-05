from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from .util import canonicalise_url, hash_payload, normalise_space, stable_external_id

STATUS_WORDS = ("forthcoming", "open", "closed", "evaluation", "results")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text(strip=True))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            graph = payload.get("@graph")
            if isinstance(graph, list):
                records.extend(item for item in graph if isinstance(item, dict))
            records.append(payload)
        elif isinstance(payload, list):
            records.extend(item for item in payload if isinstance(item, dict))
    return records


def _find_ld_type(soup: BeautifulSoup, type_name: str) -> dict[str, Any] | None:
    for item in _json_ld(soup):
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if type_name in types:
            return item
    return None


def _canonical_url(soup: BeautifulSoup, fetched_url: str) -> str:
    canonical = soup.select_one('link[rel="canonical"][href]')
    return canonicalise_url(fetched_url, canonical["href"] if canonical else fetched_url)


def _title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if not h1:
        raise ValueError("Page has no h1 title")
    return normalise_space(h1.get_text(" ", strip=True)) or "Untitled"


def _meta_description(soup: BeautifulSoup) -> str | None:
    meta = soup.select_one('meta[name="description"][content]')
    return normalise_space(meta.get("content")) if meta else None


def _first_meaningful_text_after(element: Tag) -> str | None:
    for sibling in element.find_all_next(limit=8):
        if sibling.name in {"p", "div", "h2", "h3"}:
            text = normalise_space(sibling.get_text(" ", strip=True))
            if text and text.lower() not in {"page content", "funded"}:
                return text
    return None


def _text_under_heading(soup: BeautifulSoup, heading_pattern: str) -> str | None:
    regex = re.compile(heading_pattern, re.I)
    heading = next(
        (h for h in soup.find_all(["h2", "h3", "h4"]) if regex.search(h.get_text(" ", strip=True))),
        None,
    )
    if not heading:
        return None
    chunks: list[str] = []
    for sibling in heading.find_next_siblings():
        if sibling.name in {"h2", "h3", "h4"}:
            break
        text = normalise_space(sibling.get_text(" ", strip=True))
        if text:
            chunks.append(text)
    return normalise_space(" ".join(chunks))


def _links(soup: BeautifulSoup, base_url: str, suffix: str | None = None) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = canonicalise_url(base_url, anchor.get("href", ""))
        if suffix and not urlsplit(href).path.lower().endswith(suffix.lower()):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append({"title": normalise_space(anchor.get_text(" ", strip=True)) or href, "url": href})
    return links


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = normalise_space(value) or ""
    # A month/year value is a period marker rather than an exact day. Use day 1
    # deterministically instead of dateutil inheriting today's day-of-month.
    if re.fullmatch(r"[A-Za-z]+\s+20\d{2}", cleaned):
        cleaned = f"1 {cleaned}"
    try:
        parsed = date_parser.parse(cleaned, fuzzy=True, dayfirst=True)
    except (ValueError, OverflowError):
        return None
    return parsed.date().isoformat()


def _extract_date_by_patterns(text: str, patterns: Iterable[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return _parse_iso_date(match.group(1))
    return None


def parse_call(html: str, fetched_url: str, retrieved_at: str) -> dict[str, Any]:
    soup = _soup(html)
    canonical_url = _canonical_url(soup, fetched_url)
    title = _title(soup)
    h1 = soup.find("h1")
    subtitle = _first_meaningful_text_after(h1) if h1 else None
    body_text = normalise_space(soup.get_text(" ", strip=True)) or ""
    lower_body = body_text.lower()
    status = next((word for word in STATUS_WORDS if re.search(rf"\b{word}\b", lower_body[:2500])), None)
    if title.lower().endswith("2026") and "will open" in lower_body:
        status = "forthcoming"

    opening_date = _extract_date_by_patterns(
        body_text,
        [
            r"(?:will open|opens|Stage 1 opens).*?((?:\d{1,2}\s+)?[A-Za-z]+\s+\d{4})",
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}).{0,40}Stage 1 opens",
        ],
    )
    stage1_deadline = _extract_date_by_patterns(
        body_text,
        [
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+Stage 1 closes",
            r"Stage 1 closes.{0,40}?(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"closes on (\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        ],
    )
    stage2_opening = _extract_date_by_patterns(
        body_text,
        [
            r"((?:\d{1,2}\s+)?[A-Za-z]+\s+\d{4})\s+Stage 2 opens",
            r"Stage 2 opens.{0,40}?((?:\d{1,2}\s+)?[A-Za-z]+\s+\d{4})",
        ],
    )
    stage2_deadline = _extract_date_by_patterns(
        body_text,
        [
            r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+Stage 2 closes",
            r"Stage 2 closes.{0,40}?(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            r"closes on (\d{1,2}\s+[A-Za-z]+\s+\d{4}).{0,80}(?:Stage 2|full proposal)",
        ],
    )

    topics: list[str] = []
    for heading in soup.find_all(["h2", "h3"]):
        heading_text = normalise_space(heading.get_text(" ", strip=True)) or ""
        if "call topics" in heading_text.lower():
            for item in heading.find_all_next("li", limit=8):
                item_text = normalise_space(item.get_text(" ", strip=True))
                if item_text and item_text not in topics:
                    topics.append(item_text)

    documents = _links(soup, canonical_url, suffix=".pdf")
    participating = _text_under_heading(soup, r"^Participating Countries$")

    source_payload = {
        "title": title,
        "subtitle": subtitle,
        "status": status,
        "opening_date": opening_date,
        "stage1_deadline": stage1_deadline,
        "stage2_opening": stage2_opening,
        "stage2_deadline": stage2_deadline,
        "topics": topics,
        "documents": documents,
        "participating_countries_text": participating,
    }
    return {
        "external_id": stable_external_id("call", canonical_url),
        "content_type": "call",
        "title": title,
        "subtitle": subtitle,
        "canonical_url": canonical_url,
        "status": status,
        "opening_date": opening_date,
        "stage1_deadline": stage1_deadline,
        "stage2_opening": stage2_opening,
        "stage2_deadline": stage2_deadline,
        "participating_countries_text": participating,
        "topics_json": json.dumps(topics, ensure_ascii=False),
        "documents_json": json.dumps(documents, ensure_ascii=False),
        "source_description": _meta_description(soup),
        "source_status": "active",
        "retrieved_at": retrieved_at,
        "content_hash": hash_payload(source_payload),
    }


def _extract_label_value(soup: BeautifulSoup, label: str) -> str | None:
    regex = re.compile(rf"^{re.escape(label)}$", re.I)
    for element in soup.find_all(string=lambda value: value and regex.match(normalise_space(value) or "")):
        parent = element.parent
        if not parent:
            continue
        for candidate in [parent.find_next_sibling(), parent.find_next()]:
            if candidate:
                text = normalise_space(candidate.get_text(" ", strip=True))
                if text and text.lower() != label.lower():
                    return text
    return None


def parse_event(html: str, fetched_url: str, retrieved_at: str) -> dict[str, Any]:
    soup = _soup(html)
    canonical_url = _canonical_url(soup, fetched_url)
    title = _title(soup)
    event_ld = _find_ld_type(soup, "Event") or {}

    start_date = _parse_iso_date(str(event_ld.get("startDate") or ""))
    end_date = _parse_iso_date(str(event_ld.get("endDate") or ""))
    date_text = _extract_label_value(soup, "Date")
    time_text = _extract_label_value(soup, "Time")
    location = _extract_label_value(soup, "Location")

    if not start_date and date_text:
        year_match = re.search(r"\b(20\d{2})\b", soup.get_text(" ", strip=True))
        date_for_parse = f"{date_text} {year_match.group(1)}" if year_match else date_text
        start_date = _parse_iso_date(date_for_parse)

    event_location = event_ld.get("location")
    if isinstance(event_location, dict):
        location = normalise_space(
            str(event_location.get("name") or event_location.get("address") or location or "")
        )

    links = _links(soup, canonical_url)
    registration = next(
        (
            link["url"]
            for link in links
            if any(token in link["title"].lower() for token in ("register", "registration", "expression of interest"))
        ),
        None,
    )
    body_text = normalise_space(soup.get_text(" ", strip=True)) or ""
    mode = "online" if "online" in (location or "").lower() or re.search(r"\bonline\b", body_text[:1200], re.I) else "on-site"
    excerpt = _meta_description(soup)
    if not excerpt:
        h1 = soup.find("h1")
        excerpt = _first_meaningful_text_after(h1) if h1 else None

    source_payload = {
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "date_text": date_text,
        "time_text": time_text,
        "location": location,
        "mode": mode,
        "registration_url": registration,
        "description_excerpt": excerpt,
    }
    return {
        "external_id": stable_external_id("event", canonical_url),
        "content_type": "event",
        "title": title,
        "canonical_url": canonical_url,
        "start_date": start_date,
        "end_date": end_date,
        "date_text": date_text,
        "time_text": time_text,
        "location": location,
        "mode": mode,
        "registration_url": registration,
        "description_excerpt": excerpt,
        "source_status": "active",
        "retrieved_at": retrieved_at,
        "content_hash": hash_payload(source_payload),
    }


def parse_library(html: str, fetched_url: str, retrieved_at: str) -> list[dict[str, Any]]:
    soup = _soup(html)
    canonical_url = _canonical_url(soup, fetched_url)
    publications: list[dict[str, Any]] = []
    seen: set[str] = set()

    for anchor in soup.select('a[href$=".pdf"], a[href*=".pdf?"]'):
        document_url = canonicalise_url(canonical_url, anchor.get("href", ""))
        if document_url in seen:
            continue
        seen.add(document_url)
        title = normalise_space(anchor.get_text(" ", strip=True)) or urlsplit(document_url).path.rsplit("/", 1)[-1]
        title = re.sub(r"\s*\(pdf[^)]*\)\s*$", "", title, flags=re.I)
        category = "DUT Publications"
        preceding_heading = anchor.find_previous(["h2", "h3"])
        if preceding_heading:
            category = normalise_space(preceding_heading.get_text(" ", strip=True)) or category
        size_match = re.search(r"\((pdf\s+[^)]+)\)", anchor.get_text(" ", strip=True), re.I)
        source_payload = {"title": title, "category": category, "document_url": document_url}
        publications.append(
            {
                "external_id": stable_external_id("publication", document_url),
                "content_type": "publication",
                "title": title,
                "category": category,
                "document_url": document_url,
                "file_type": "pdf",
                "file_size_text": size_match.group(1) if size_match else None,
                "canonical_url": canonical_url,
                "source_status": "active",
                "retrieved_at": retrieved_at,
                "content_hash": hash_payload(source_payload),
            }
        )
    return sorted(publications, key=lambda item: (item["category"], item["title"].lower()))
