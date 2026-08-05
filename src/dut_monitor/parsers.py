from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import parse_qsl, parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from .util import canonicalise_url, hash_payload, normalise_space, stable_external_id

MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_WITH_YEAR_PATTERN = rf"(?:\d{{1,2}}\s+)?{MONTH_PATTERN}\s+20\d{{2}}"
FULL_DATE_PATTERN = rf"\d{{1,2}}\s+{MONTH_PATTERN}\s+20\d{{2}}"


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


def _content_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    return soup.find("main") or soup.find("article") or soup.body or soup


def _first_meaningful_text_after(element: Tag) -> str | None:
    excluded = {
        "page content",
        "funded",
        "funded projects",
        "call statistics",
        "online",
        "on-site",
        "onsite",
        "hybrid",
        "date",
        "time",
        "location",
    }
    for candidate in element.find_all_next(limit=30):
        if candidate.name in {"h2", "h3"}:
            break
        if candidate.name not in {"p", "div"}:
            continue
        text = normalise_space(candidate.get_text(" ", strip=True))
        if not text or text.lower() in excluded:
            continue
        if 12 <= len(text) <= 400:
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
    level = int(heading.name[1])
    chunks: list[str] = []
    for element in heading.find_all_next():
        if element is heading:
            continue
        if element.name in {"h2", "h3", "h4"} and int(element.name[1]) <= level:
            break
        if element.name in {"p", "li"}:
            text = normalise_space(element.get_text(" ", strip=True))
            if text and text not in chunks:
                chunks.append(text)
    return normalise_space(" ".join(chunks))


def _list_items_under_heading(heading: Tag, limit: int = 12) -> list[str]:
    level = int(heading.name[1])
    items: list[str] = []
    for element in heading.find_all_next():
        if element is heading:
            continue
        if element.name in {"h2", "h3", "h4"} and int(element.name[1]) <= level:
            break
        if element.name != "li":
            continue
        text = normalise_space(element.get_text(" ", strip=True))
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


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
    if re.fullmatch(rf"{MONTH_PATTERN}\s+20\d{{2}}", cleaned, flags=re.I):
        cleaned = f"1 {cleaned}"
    try:
        parsed = date_parser.parse(cleaned, fuzzy=True, dayfirst=True)
    except (ValueError, OverflowError):
        return None
    return parsed.date().isoformat()


def _extract_date_by_patterns(texts: Iterable[str], patterns: Iterable[str]) -> str | None:
    for text in texts:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return _parse_iso_date(match.group("date") if "date" in match.groupdict() else match.group(1))
    return None


def _call_dates(soup: BeautifulSoup, body_text: str) -> tuple[str | None, str | None, str | None, str | None]:
    timeline_items = [normalise_space(item.get_text(" ", strip=True)) or "" for item in soup.find_all("li")]
    texts = [*timeline_items, body_text]

    opening_date = _extract_date_by_patterns(
        texts,
        [
            rf"(?P<date>{DATE_WITH_YEAR_PATTERN})\s+Stage\s*1\s+opens\b",
            rf"Stage\s*1\s+opens[^.;]{{0,80}}?(?P<date>{DATE_WITH_YEAR_PATTERN})",
            rf"(?:call|first stage)\s+(?:will\s+)?open(?:s)?\s+on\s+(?P<date>{FULL_DATE_PATTERN})",
        ],
    )
    stage1_deadline = _extract_date_by_patterns(
        texts,
        [
            rf"(?P<date>{FULL_DATE_PATTERN})\s+Stage\s*1\s+closes\b",
            rf"Stage\s*1\s+closes[^.;]{{0,80}}?(?P<date>{FULL_DATE_PATTERN})",
            rf"first stage[^.;]{{0,100}}?closes\s+on\s+(?P<date>{FULL_DATE_PATTERN})",
        ],
    )
    stage2_opening = _extract_date_by_patterns(
        texts,
        [
            rf"(?P<date>{DATE_WITH_YEAR_PATTERN})\s+Stage\s*2\s+opens\b",
            rf"Stage\s*2\s+opens[^.;]{{0,80}}?(?P<date>{DATE_WITH_YEAR_PATTERN})",
            rf"Stage\s*2\s+opens[^.;]{{0,100}}?in\s+(?P<date>{MONTH_PATTERN}\s+20\d{{2}})",
        ],
    )
    stage2_deadline = _extract_date_by_patterns(
        texts,
        [
            rf"(?P<date>{FULL_DATE_PATTERN})\s+Stage\s*2\s+closes\b",
            rf"Stage\s*2\s+closes[^.;]{{0,80}}?(?P<date>{FULL_DATE_PATTERN})",
            rf"Stage\s*2[^.;]{{0,100}}?closes\s+on\s+(?P<date>{FULL_DATE_PATTERN})",
        ],
    )
    return opening_date, stage1_deadline, stage2_opening, stage2_deadline


def _derive_call_status(
    title: str,
    body_text: str,
    retrieved_at: str,
    opening_date: str | None,
    stage1_deadline: str | None,
    stage2_opening: str | None,
    stage2_deadline: str | None,
    documents: list[dict[str, str]],
) -> str:
    try:
        today = date_parser.parse(retrieved_at).date()
    except (ValueError, OverflowError):
        today = datetime.utcnow().date()

    def parsed(value: str | None) -> date | None:
        return date.fromisoformat(value) if value else None

    opening = parsed(opening_date)
    first_close = parsed(stage1_deadline)
    second_open = parsed(stage2_opening)
    second_close = parsed(stage2_deadline)
    result_evidence = " ".join(document["title"].lower() for document in documents)
    result_evidence += " " + body_text[:3500].lower()

    if any(token in result_evidence for token in ("projects suggested for funding", "funded projects")):
        return "results"
    if opening and today < opening:
        return "forthcoming"
    if second_close and today > second_close:
        return "closed"
    if second_open and second_close and second_open <= today <= second_close:
        return "open"
    if first_close and today > first_close and (not second_open or today < second_open):
        return "evaluation"
    if opening and first_close and opening <= today <= first_close:
        return "open"

    year_match = re.search(r"\b(20\d{2})\b", title)
    if year_match:
        call_year = int(year_match.group(1))
        if call_year > today.year:
            return "forthcoming"
        if call_year < today.year:
            return "closed"
    return "open" if re.search(r"\bcall is open\b", body_text[:3000], re.I) else "unknown"


def parse_call(html: str, fetched_url: str, retrieved_at: str) -> dict[str, Any]:
    soup = _soup(html)
    canonical_url = _canonical_url(soup, fetched_url)
    title = _title(soup)
    h1 = soup.find("h1")
    subtitle = _first_meaningful_text_after(h1) if h1 else None
    root = _content_root(soup)
    body_text = normalise_space(root.get_text(" ", strip=True)) or ""

    opening_date, stage1_deadline, stage2_opening, stage2_deadline = _call_dates(soup, body_text)

    topics: list[str] = []
    rejected_topic_tokens = {
        "legal notice",
        "contact",
        "privacy policy",
        "press",
        "accessibilty",
        "accessibility",
        "youtube",
        "linkedin",
    }
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = normalise_space(heading.get_text(" ", strip=True)) or ""
        if "call topics" not in heading_text.lower():
            continue
        for item_text in _list_items_under_heading(heading):
            lowered = item_text.lower()
            if lowered in rejected_topic_tokens or ".pdf" in lowered or len(item_text) > 260:
                continue
            if item_text not in topics:
                topics.append(item_text)

    documents = _links(soup, canonical_url, suffix=".pdf")
    participating = _text_under_heading(soup, r"^Participating Countries$")
    status = _derive_call_status(
        title,
        body_text,
        retrieved_at,
        opening_date,
        stage1_deadline,
        stage2_opening,
        stage2_deadline,
        documents,
    )

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


def _parse_date_range(value: str | None, year_hint: int | None = None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    text = normalise_space(value) or ""
    text = text.replace("—", "–")

    range_match = re.fullmatch(
        rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s*[–-]\s*(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+(20\d{{2}}))?",
        text,
        flags=re.I,
    )
    if range_match:
        first_day, first_month, second_day, second_month, year_text = range_match.groups()
        year = int(year_text) if year_text else year_hint
        if not year:
            return None, None
        start = _parse_iso_date(f"{first_day} {first_month} {year}")
        end = _parse_iso_date(f"{second_day} {second_month} {year}")
        return start, end

    compact_range = re.fullmatch(
        rf"(\d{{1,2}})\s*[–-]\s*(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+(20\d{{2}}))?",
        text,
        flags=re.I,
    )
    if compact_range:
        first_day, second_day, month, year_text = compact_range.groups()
        year = int(year_text) if year_text else year_hint
        if not year:
            return None, None
        return (
            _parse_iso_date(f"{first_day} {month} {year}"),
            _parse_iso_date(f"{second_day} {month} {year}"),
        )

    if not re.search(r"\b20\d{2}\b", text):
        if not year_hint:
            return None, None
        text = f"{text} {year_hint}"
    return _parse_iso_date(text), None


def _event_year_hint(title: str, date_text: str | None, main_text: str, retrieved_at: str) -> int | None:
    direct_year = re.search(r"\b(20\d{2})\b", date_text or "")
    if direct_year:
        return int(direct_year.group(1))

    day_month_match = re.search(rf"\b(\d{{1,2}})\s+({MONTH_PATTERN})\b", date_text or "", re.I)
    if day_month_match:
        expected_day = int(day_month_match.group(1))
        expected_month = date_parser.parse(day_month_match.group(2), fuzzy=True).month
        for candidate in re.findall(FULL_DATE_PATTERN, main_text, flags=re.I):
            parsed = date_parser.parse(candidate, fuzzy=True, dayfirst=True)
            if parsed.day == expected_day and parsed.month == expected_month:
                return parsed.year

    try:
        max_reasonable_year = date_parser.parse(retrieved_at).year + 2
    except (ValueError, OverflowError):
        max_reasonable_year = datetime.utcnow().year + 2
    title_year = re.search(r"\b(20\d{2})\b", title)
    if title_year and 2020 <= int(title_year.group(1)) <= max_reasonable_year:
        return int(title_year.group(1))
    return None


def _event_mode(location: str | None, main_text: str) -> str:
    context = normalise_space(" ".join(filter(None, [location, main_text[:1800]]))) or ""
    lower = context.lower()
    if "hybrid" in lower:
        return "hybrid"
    if re.search(r"\bonline\b", lower):
        return "online"
    if location or re.search(r"\bon[- ]?site\b", lower):
        return "on-site"
    return "unspecified"


def parse_event(html: str, fetched_url: str, retrieved_at: str) -> dict[str, Any]:
    soup = _soup(html)
    canonical_url = _canonical_url(soup, fetched_url)
    title = _title(soup)
    event_ld = _find_ld_type(soup, "Event") or {}
    root = _content_root(soup)
    main_text = normalise_space(root.get_text(" ", strip=True)) or ""

    start_date = _parse_iso_date(str(event_ld.get("startDate") or ""))
    end_date = _parse_iso_date(str(event_ld.get("endDate") or ""))
    date_text = _extract_label_value(soup, "Date")
    time_text = _extract_label_value(soup, "Time")
    location = _extract_label_value(soup, "Location")

    if not start_date and date_text:
        year_hint = _event_year_hint(title, date_text, main_text, retrieved_at)
        parsed_start, parsed_end = _parse_date_range(date_text, year_hint)
        start_date = parsed_start
        end_date = end_date or parsed_end

    event_location = event_ld.get("location")
    if isinstance(event_location, dict):
        address = event_location.get("address")
        if isinstance(address, dict):
            address = ", ".join(
                str(address.get(key))
                for key in ("streetAddress", "addressLocality", "addressCountry")
                if address.get(key)
            )
        location = normalise_space(str(event_location.get("name") or address or location or ""))

    links = _links(soup, canonical_url)
    registration = next(
        (
            link["url"]
            for link in links
            if any(token in link["title"].lower() for token in ("register", "registration", "expression of interest"))
        ),
        None,
    )
    mode = _event_mode(location, main_text)
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

WEBINAR_TITLE_PATTERN = re.compile(r"\burban lunch talks?\b", re.I)
PORTUGUESE_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
PORTUGUESE_SEASONS = {
    "inverno": 1,
    "primavera": 4,
    "verao": 7,
    "verão": 7,
    "outono": 10,
}
NEWSLETTER_HOST_SUFFIXES = ("mailchi.mp", "campaign-archive.com")


def is_webinar_title(title: str | None) -> bool:
    return bool(title and WEBINAR_TITLE_PATTERN.search(title))


def _normalise_youtube_url(candidate: str, base_url: str) -> str | None:
    if not candidate:
        return None
    absolute = urljoin(base_url, candidate.replace("&amp;", "&"))
    parts = urlsplit(absolute)
    host = parts.netloc.lower().split(":", 1)[0]
    video_id: str | None = None
    if host.endswith("youtu.be"):
        video_id = parts.path.strip("/").split("/", 1)[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parts.path == "/watch":
            video_id = (parse_qs(parts.query).get("v") or [None])[0]
        else:
            match = re.search(r"/(?:embed|shorts)/([A-Za-z0-9_-]{6,})", parts.path)
            if match:
                video_id = match.group(1)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def _extract_youtube_url(soup: BeautifulSoup, canonical_url: str, html: str) -> str | None:
    candidates: list[str] = []
    for element in soup.find_all(True):
        for attr in ("href", "src", "data-src", "data-video-url", "data-cookieblock-src"):
            value = element.get(attr)
            if isinstance(value, str) and ("youtu" in value.lower()):
                candidates.append(value)
    candidates.extend(
        match.group(0)
        for match in re.finditer(
            r"https?://(?:www\.)?(?:youtube(?:-nocookie)?\.com/(?:watch\?[^\"'\s<>]*v=|embed/|shorts/)|youtu\.be/)[A-Za-z0-9_?&=./%-]+",
            html,
            flags=re.I,
        )
    )
    for candidate in candidates:
        normalised = _normalise_youtube_url(candidate, canonical_url)
        if normalised:
            return normalised
    return None


def _section_items(soup: BeautifulSoup, heading_pattern: str, limit: int = 40) -> list[str]:
    regex = re.compile(heading_pattern, re.I)
    heading = next(
        (h for h in soup.find_all(["h2", "h3", "h4"]) if regex.search(normalise_space(h.get_text(" ", strip=True)) or "")),
        None,
    )
    if not heading:
        return []
    level = int(heading.name[1])
    values: list[str] = []
    for element in heading.find_all_next():
        if element is heading:
            continue
        if element.name in {"h2", "h3", "h4"} and int(element.name[1]) <= level:
            break
        if element.name not in {"li", "p"}:
            continue
        text = normalise_space(element.get_text(" ", strip=True))
        if not text or text.lower().startswith("moderator:"):
            continue
        if text not in values:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _moderator(soup: BeautifulSoup) -> str | None:
    root = _content_root(soup)
    for element in root.find_all(["p", "li", "div"]):
        text = normalise_space(element.get_text(" ", strip=True))
        if text and re.match(r"^moderator\s*:", text, flags=re.I):
            return normalise_space(re.sub(r"^moderator\s*:\s*", "", text, flags=re.I))
    return None


def parse_webinar(html: str, fetched_url: str, retrieved_at: str) -> dict[str, Any]:
    soup = _soup(html)
    base = parse_event(html, fetched_url, retrieved_at)
    title = base["title"]
    if not is_webinar_title(title):
        raise ValueError("Event is not an Urban Lunch Talk webinar")
    canonical_url = base["canonical_url"]
    episode_match = re.search(r"urban lunch talks?\s*#\s*(\d+)", title, flags=re.I)
    episode_number = int(episode_match.group(1)) if episode_match else None
    recording_url = _extract_youtube_url(soup, canonical_url, html)
    speakers = _section_items(soup, r"^Speakers?\b")
    moderator = _moderator(soup)
    source_payload = {
        "series": "Urban Lunch Talks",
        "episode_number": episode_number,
        "title": title,
        "canonical_url": canonical_url,
        "event_date": base.get("start_date"),
        "end_date": base.get("end_date"),
        "date_text": base.get("date_text"),
        "time_text": base.get("time_text"),
        "recording_url": recording_url,
        "registration_url": base.get("registration_url"),
        "speakers": speakers,
        "moderator": moderator,
        "description_excerpt": base.get("description_excerpt"),
    }
    return {
        "external_id": stable_external_id("webinar", canonical_url),
        "content_type": "webinar",
        "series": "Urban Lunch Talks",
        "episode_number": episode_number,
        "title": title,
        "canonical_url": canonical_url,
        "source_event_id": base["external_id"],
        "event_date": base.get("start_date"),
        "end_date": base.get("end_date"),
        "date_text": base.get("date_text"),
        "time_text": base.get("time_text"),
        "recording_url": recording_url,
        "recording_status": "available" if recording_url else "not_found",
        "registration_url": base.get("registration_url"),
        "speakers_json": json.dumps(speakers, ensure_ascii=False),
        "moderator": moderator,
        "description_excerpt": base.get("description_excerpt"),
        "source_status": "active",
        "retrieved_at": retrieved_at,
        "content_hash": hash_payload(source_payload),
    }


def _clean_newsletter_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, href.strip())
    parts = urlsplit(absolute)
    clean_query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key.lower() != "e"])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, clean_query, ""))


def _newsletter_period(label: str) -> tuple[int | None, int | None, str, str | None]:
    lowered = label.casefold()
    year_match = re.search(r"\b(20\d{2})\b", label)
    year = int(year_match.group(1)) if year_match else None
    month: int | None = None
    period_type = "unknown"
    for name, number in PORTUGUESE_MONTHS.items():
        if name in lowered:
            month = number
            period_type = "month"
            break
    if month is None:
        for name, number in PORTUGUESE_SEASONS.items():
            if name in lowered:
                month = number
                period_type = "season"
                break
    sort_date = f"{year:04d}-{month:02d}-01" if year and month else None
    return year, month, period_type, sort_date


def parse_regional_newsletters(html: str, fetched_url: str, retrieved_at: str) -> list[dict[str, Any]]:
    soup = _soup(html)
    source_page_url = _canonical_url(soup, fetched_url)
    heading = next(
        (
            h
            for h in soup.find_all(["h2", "h3", "h4"])
            if re.fullmatch(r"newsletters", normalise_space(h.get_text(" ", strip=True)) or "", flags=re.I)
        ),
        None,
    )
    if not heading:
        raise ValueError("Regional DUT page has no NEWSLETTERS section")
    level = int(heading.name[1])
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element in heading.find_all_next():
        if element is heading:
            continue
        if element.name in {"h2", "h3", "h4"} and int(element.name[1]) <= level:
            break
        if element.name != "a" or not element.get("href"):
            continue
        label = normalise_space(element.get_text(" ", strip=True))
        if not label:
            continue
        archive_url = _clean_newsletter_url(source_page_url, element.get("href", ""))
        host = urlsplit(archive_url).netloc.lower()
        if not any(host == suffix or host.endswith("." + suffix) for suffix in NEWSLETTER_HOST_SUFFIXES):
            continue
        key = (label.casefold(), archive_url)
        if key in seen:
            continue
        seen.add(key)
        issue_year, issue_month, period_type, sort_date = _newsletter_period(label)
        identity = f"{archive_url}#{label.casefold()}"
        source_payload = {
            "issue_label": label,
            "issue_year": issue_year,
            "issue_month": issue_month,
            "issue_period": period_type,
            "issue_sort_date": sort_date,
            "archive_url": archive_url,
            "source_page_url": source_page_url,
        }
        records.append(
            {
                "external_id": stable_external_id("newsletter", identity),
                "content_type": "newsletter",
                "issue_label": label,
                "issue_year": issue_year,
                "issue_month": issue_month,
                "issue_period": period_type,
                "issue_sort_date": sort_date,
                "archive_url": archive_url,
                "archive_host": host,
                "source_page_url": source_page_url,
                "source_status": "active",
                "retrieved_at": retrieved_at,
                "content_hash": hash_payload(source_payload),
            }
        )
    return sorted(
        records,
        key=lambda item: (item.get("issue_sort_date") or "0000-00-00", item["issue_label"]),
        reverse=True,
    )

