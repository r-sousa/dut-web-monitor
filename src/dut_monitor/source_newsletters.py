from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .util import canonicalise_url, hash_payload, normalise_space, read_json, stable_external_id, write_json

ARCHIVE_HOST_SUFFIXES = ("mailchi.mp", "campaign-archive.com")
MONTHS = {
    "january": 1, "jan": 1, "janeiro": 1, "february": 2, "feb": 2, "fevereiro": 2,
    "march": 3, "mar": 3, "marco": 3, "março": 3, "april": 4, "apr": 4, "abril": 4,
    "may": 5, "maio": 5, "june": 6, "jun": 6, "junho": 6, "july": 7, "jul": 7, "julho": 7,
    "august": 8, "aug": 8, "agosto": 8, "september": 9, "sep": 9, "setembro": 9,
    "october": 10, "oct": 10, "outubro": 10, "november": 11, "nov": 11, "novembro": 11,
    "december": 12, "dec": 12, "dezembro": 12,
}
SEASONS = {"winter": 1, "inverno": 1, "spring": 4, "primavera": 4, "summer": 7, "verao": 7, "verão": 7, "autumn": 10, "fall": 10, "outono": 10}

def _clean_archive_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href.strip())
    parts = urlsplit(absolute)
    clean_query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query) if key.lower() not in {"e", "mc_cid", "mc_eid"}]
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, clean_query, ""))


def _newsletter_period(label: str, archive_url: str = "") -> tuple[int | None, int | None, str, str | None]:
    combined = f"{label} {urlsplit(archive_url).path}".casefold().replace("-", " ").replace("_", " ")
    year_match = re.search(r"\b(20\d{2})\b", combined)
    year = int(year_match.group(1)) if year_match else None
    month = None
    period = "unknown"
    for token, number in MONTHS.items():
        if re.search(rf"\b{re.escape(token)}\b", combined):
            month = number
            period = "month"
            break
    if month is None:
        for token, number in SEASONS.items():
            if re.search(rf"\b{re.escape(token)}\b", combined):
                month = number
                period = "season"
                break
    sort_date = f"{year:04d}-{month:02d}-01" if year and month else None
    return year, month, period, sort_date


def _newsletter_record(
    issue_label: str,
    archive_url: str,
    source_page_url: str | None,
    retrieved_at: str,
    source_priority: int,
    source_role: str,
    source_name: str,
) -> dict[str, Any]:
    year, month, period, sort_date = _newsletter_period(issue_label, archive_url)
    payload = {
        "issue_label": issue_label,
        "archive_url": archive_url,
        "issue_sort_date": sort_date,
        "source_priority": source_priority,
        "source_role": source_role,
        "source_name": source_name,
    }
    return {
        "external_id": stable_external_id("newsletter", f"{archive_url}#{issue_label}"),
        "content_type": "newsletter",
        "issue_label": issue_label,
        "issue_year": year,
        "issue_month": month,
        "issue_period": period,
        "issue_sort_date": sort_date,
        "archive_url": archive_url,
        "archive_host": urlsplit(archive_url).netloc.lower(),
        "source_page_url": source_page_url,
        "source_priority": source_priority,
        "source_role": source_role,
        "source_name": source_name,
        "source_status": "active",
        "retrieved_at": retrieved_at,
        "content_hash": hash_payload(payload),
    }


def parse_primary_newsletters(html: str, fetched_url: str, retrieved_at: str) -> list[dict[str, Any]]:
    """Extract newsletter archives exposed directly by the European DUT site."""
    soup = BeautifulSoup(html, "lxml")
    canonical = soup.select_one('link[rel="canonical"][href]')
    source_page_url = canonicalise_url(fetched_url, canonical["href"] if canonical else fetched_url)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        archive_url = _clean_archive_url(source_page_url, anchor.get("href", ""))
        host = urlsplit(archive_url).netloc.lower()
        if not any(host == suffix or host.endswith(f".{suffix}") for suffix in ARCHIVE_HOST_SUFFIXES):
            continue
        if archive_url in seen:
            continue
        seen.add(archive_url)
        label = normalise_space(anchor.get_text(" ", strip=True)) or urlsplit(archive_url).path.rsplit("/", 1)[-1]
        records.append(_newsletter_record(label, archive_url, source_page_url, retrieved_at, 1, "primary_european", "DUT Partnership"))
    return sorted(records, key=lambda item: (item.get("issue_sort_date") or "9999-12-31", item["issue_label"]))


def load_manual_newsletters(path: Path, retrieved_at: str) -> list[dict[str, Any]]:
    records = []
    for item in read_json(path, []):
        label = normalise_space(str(item.get("issue_label") or ""))
        raw_url = str(item.get("archive_url") or "").strip()
        if not label or not raw_url:
            continue
        archive_url = _clean_archive_url("https://dutpartnership.eu", raw_url)
        records.append(_newsletter_record(label, archive_url, str(item.get("source_page_url") or "manual://ccdr-norte"), retrieved_at, 2, "secondary_manual", "CCDR NORTE manual update"))
    return records


def _rebuild_legacy_newsletter(item: dict[str, Any], retrieved_at: str) -> dict[str, Any] | None:
    label = normalise_space(str(item.get("issue_label") or ""))
    raw_url = str(item.get("archive_url") or "").strip()
    if not label or not raw_url:
        return None
    archive_url = _clean_archive_url("https://dutpartnership.eu", raw_url)
    return _newsletter_record(
        label,
        archive_url,
        str(item.get("source_page_url") or "https://www.ccdr-n.pt/pagina/outra-documentacao-relevante-dut"),
        retrieved_at,
        3,
        "legacy_regional_backfill",
        "CCDR NORTE legacy archive",
    )


def load_or_freeze_legacy_newsletters(path: Path, existing_public_records: list[dict[str, Any]], retrieved_at: str) -> list[dict[str, Any]]:
    raw = read_json(path, [])
    if not raw and existing_public_records:
        raw = [
            {"issue_label": item.get("issue_label"), "archive_url": item.get("archive_url"), "source_page_url": item.get("source_page_url")}
            for item in existing_public_records
            if item.get("issue_label") and item.get("archive_url")
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, raw)
    records = []
    for item in raw:
        rebuilt = _rebuild_legacy_newsletter(item, retrieved_at)
        if rebuilt:
            records.append(rebuilt)
    return records


def merge_newsletters(*layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_archive: dict[str, dict[str, Any]] = {}
    for layer in layers:
        for item in layer:
            key = item["archive_url"]
            current = by_archive.get(key)
            if current is None or item["source_priority"] < current["source_priority"]:
                by_archive[key] = item
    return sorted(by_archive.values(), key=lambda item: (item.get("issue_sort_date") or "9999-12-31", item["issue_label"]))
