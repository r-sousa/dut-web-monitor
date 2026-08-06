from __future__ import annotations

from collections import deque
from urllib.parse import urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .config import Settings
from .http import PoliteClient
from .util import canonicalise_url


def _same_host(url: str, base_url: str) -> bool:
    return urlsplit(url).netloc.lower() == urlsplit(base_url).netloc.lower()


def discover_from_sitemaps(client: PoliteClient, settings: Settings) -> set[str]:
    discovered: set[str] = set()
    queue: deque[str] = deque(
        canonicalise_url(settings.base_url, path) for path in settings.sitemap_paths
    )
    visited: set[str] = set()

    while queue and len(visited) < 20:
        sitemap_url = queue.popleft()
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)
        try:
            result = client.get(sitemap_url)
        except Exception:
            continue
        try:
            root = ElementTree.fromstring(result.text)
        except ElementTree.ParseError:
            continue
        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag.split("}", 1)[0] + "}"
        locs = [element.text.strip() for element in root.findall(f".//{namespace}loc") if element.text]
        if root.tag.endswith("sitemapindex"):
            queue.extend(locs)
        else:
            for url in locs:
                canonical = canonicalise_url(settings.base_url, url)
                if _same_host(canonical, settings.base_url):
                    discovered.add(canonical)
    return discovered


def discover_links_from_index(
    client: PoliteClient,
    settings: Settings,
    path: str,
    allowed_prefixes: tuple[str, ...],
) -> set[str]:
    index_url = canonicalise_url(settings.base_url, path)
    result = client.get(index_url)
    soup = BeautifulSoup(result.text, "lxml")
    links: set[str] = set()
    for anchor in soup.select("a[href]"):
        candidate = canonicalise_url(settings.base_url, anchor.get("href", ""))
        candidate_path = urlsplit(candidate).path
        if candidate != index_url and any(candidate_path.startswith(prefix) for prefix in allowed_prefixes):
            links.add(candidate)
    return links


def classify_urls(urls: set[str], settings: Settings) -> dict[str, set[str]]:
    groups = {"calls": set(), "events": set(), "news": set(), "projects": set()}
    for url in urls:
        path = urlsplit(url).path.rstrip("/")
        if path.startswith("/calls/"):
            groups["calls"].add(url)
        elif path.startswith("/events/"):
            groups["events"].add(url)
        elif path.startswith("/news/"):
            groups["news"].add(url)
        elif path.startswith("/projects/"):
            groups["projects"].add(url)
    return groups
