from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .change_detection import compare_records
from .config import SETTINGS, Settings
from .discovery import classify_urls, discover_from_sitemaps, discover_links_from_index
from .http import PoliteClient
from .parsers import is_webinar_title, parse_call, parse_event, parse_library, parse_webinar
from .source_priority import (
    annotate_primary_webinars,
    load_legacy_webinars,
    load_manual_news,
    load_manual_newsletters,
    load_or_freeze_legacy_newsletters,
    merge_news,
    merge_newsletters,
    merge_webinars,
    parse_news,
    parse_primary_newsletters,
)
from .util import hash_payload, read_json, utc_now_iso, write_json


def _collect_detail_records(
    urls: list[str],
    parser: Callable[[str, str, str], dict[str, Any]],
    client: PoliteClient,
    retrieved_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for url in urls:
        try:
            result = client.get(url)
            records.append(parser(result.text, result.url, retrieved_at))
        except Exception as exc:
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return records, errors


def _deduplicate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        by_id[record["external_id"]] = record
    return sorted(by_id.values(), key=lambda item: item["external_id"])


def run(settings: Settings = SETTINGS) -> int:
    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = utc_now_iso()
    client = PoliteClient(settings)

    sitemap_urls = discover_from_sitemaps(client, settings)
    grouped = classify_urls(sitemap_urls, settings)

    if not grouped["calls"]:
        grouped["calls"] = discover_links_from_index(client, settings, settings.calls_index, ("/calls/",))
    if not grouped["events"]:
        grouped["events"] = discover_links_from_index(client, settings, settings.events_index, ("/events/",))
    if not grouped["news"]:
        grouped["news"] = discover_links_from_index(client, settings, settings.news_index, ("/news/",))

    call_urls = sorted(grouped["calls"])[: settings.max_detail_pages_per_type]
    event_urls = sorted(grouped["events"])[: settings.max_detail_pages_per_type]
    news_urls = sorted(grouped["news"])[: settings.max_detail_pages_per_type]

    calls, call_errors = _collect_detail_records(call_urls, parse_call, client, retrieved_at)
    events, event_errors = _collect_detail_records(event_urls, parse_event, client, retrieved_at)
    primary_news, news_errors = _collect_detail_records(news_urls, parse_news, client, retrieved_at)
    news = merge_news(primary_news, load_manual_news(settings.manual_news_path, retrieved_at))

    webinar_errors: list[dict[str, str]] = []
    webinar_urls = {event["canonical_url"] for event in events if is_webinar_title(event.get("title"))}
    try:
        webinar_urls.update(
            discover_links_from_index(client, settings, settings.webinars_index, ("/events/", "/dut-events/"))
        )
    except Exception as exc:
        webinar_errors.append(
            {"url": settings.base_url.rstrip("/") + settings.webinars_index, "error": f"{type(exc).__name__}: {exc}"}
        )
    primary_webinars, webinar_detail_errors = _collect_detail_records(
        sorted(webinar_urls)[: settings.max_detail_pages_per_type], parse_webinar, client, retrieved_at
    )
    webinar_errors.extend(webinar_detail_errors)
    primary_webinars = annotate_primary_webinars(_deduplicate_records(primary_webinars))
    legacy_webinars = load_legacy_webinars(settings.legacy_webinars_path, retrieved_at)
    webinars = merge_webinars(primary_webinars, legacy_webinars)

    library_url = settings.base_url.rstrip("/") + settings.library_index
    library_result = client.get(library_url)
    publications = parse_library(library_result.text, library_result.url, retrieved_at)

    newsletter_errors: list[dict[str, str]] = []
    try:
        newsletter_url = settings.base_url.rstrip("/") + settings.newsletter_primary_path
        newsletter_result = client.get(newsletter_url)
        primary_newsletters = parse_primary_newsletters(
            newsletter_result.text, newsletter_result.url, retrieved_at
        )
    except Exception as exc:
        primary_newsletters = []
        newsletter_errors.append(
            {"url": settings.base_url.rstrip("/") + settings.newsletter_primary_path, "error": f"{type(exc).__name__}: {exc}"}
        )

    existing_newsletters = read_json(output_dir / "newsletters.json", [])
    legacy_newsletters = load_or_freeze_legacy_newsletters(
        settings.legacy_newsletters_path, existing_newsletters, retrieved_at
    )
    manual_newsletters = load_manual_newsletters(settings.manual_newsletters_path, retrieved_at)
    newsletters = merge_newsletters(primary_newsletters, manual_newsletters, legacy_newsletters)

    datasets: dict[str, list[dict[str, Any]]] = {
        "calls": calls,
        "events": events,
        "news": news,
        "publications": publications,
        "webinars": webinars,
        "newsletters": newsletters,
    }
    all_changes: list[dict[str, Any]] = []
    changed_datasets: list[str] = []

    for name, records in datasets.items():
        path = output_dir / f"{name}.json"
        old_records = read_json(path, [])
        changes = compare_records(old_records, records, name)
        if changes:
            changed_datasets.append(name)
            all_changes.extend(changes)
        write_json(path, records)

    dataset_hashes = {
        name: hash_payload([{k: v for k, v in record.items() if k != "retrieved_at"} for record in records])
        for name, records in datasets.items()
    }
    combined_hash = hash_payload(dataset_hashes)
    previous_manifest = read_json(output_dir / "manifest.json", {})
    data_changed = combined_hash != previous_manifest.get("dataset_hash")
    errors = call_errors + event_errors + news_errors + webinar_errors + newsletter_errors

    manifest = {
        "schema_version": "1.1",
        "dataset_version": retrieved_at if data_changed else previous_manifest.get("dataset_version", retrieved_at),
        "generated_at": retrieved_at if data_changed else previous_manifest.get("generated_at", retrieved_at),
        "dataset_hash": combined_hash,
        "status": "valid" if not errors else "partial",
        "changed_datasets": changed_datasets,
        "record_counts": {name: len(records) for name, records in datasets.items()},
        "dataset_hashes": dataset_hashes,
        "files": {**{name: f"{name}.json" for name in datasets}, "changes": "changes-latest.json"},
        "source": settings.base_url,
        "source_hierarchy": {
            "news": [
                {"rank": 1, "role": "primary_european", "source": settings.base_url + settings.news_index},
                {"rank": 2, "role": "secondary_manual", "source": str(settings.manual_news_path)},
            ],
            "newsletters": [
                {"rank": 1, "role": "primary_european", "source": settings.base_url + settings.newsletter_primary_path},
                {"rank": 2, "role": "secondary_manual", "source": str(settings.manual_newsletters_path)},
                {"rank": 3, "role": "legacy_regional_backfill", "source": str(settings.legacy_newsletters_path)},
            ],
            "webinars": [
                {"rank": 1, "role": "primary_european", "source": settings.base_url + settings.webinars_index},
                {"rank": 1, "role": "legacy_primary", "source": str(settings.legacy_webinars_path)},
            ],
        },
        "errors": errors,
    }
    write_json(output_dir / "changes-latest.json", all_changes)
    write_json(output_dir / "manifest.json", manifest)

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 2 if manifest["status"] == "partial" else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public DUT website metadata")
    parser.add_argument("--output", type=Path, default=Path("public"))
    args = parser.parse_args()
    settings = Settings(output_dir=args.output)
    sys.exit(run(settings))


if __name__ == "__main__":
    main()
