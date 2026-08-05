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
from .parsers import parse_call, parse_event, parse_library
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
        except Exception as exc:  # isolated source failures should be reported, not hidden
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return records, errors


def run(settings: Settings = SETTINGS) -> int:
    output_dir = settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = utc_now_iso()
    client = PoliteClient(settings)

    sitemap_urls = discover_from_sitemaps(client, settings)
    grouped = classify_urls(sitemap_urls, settings)

    if not grouped["calls"]:
        grouped["calls"] = discover_links_from_index(
            client, settings, settings.calls_index, ("/calls/",)
        )
    if not grouped["events"]:
        grouped["events"] = discover_links_from_index(
            client, settings, settings.events_index, ("/events/",)
        )

    call_urls = sorted(grouped["calls"])[: settings.max_detail_pages_per_type]
    event_urls = sorted(grouped["events"])[: settings.max_detail_pages_per_type]

    calls, call_errors = _collect_detail_records(call_urls, parse_call, client, retrieved_at)
    events, event_errors = _collect_detail_records(event_urls, parse_event, client, retrieved_at)

    library_url = settings.base_url.rstrip("/") + settings.library_index
    library_result = client.get(library_url)
    publications = parse_library(library_result.text, library_result.url, retrieved_at)

    datasets: dict[str, list[dict[str, Any]]] = {
        "calls": calls,
        "events": events,
        "publications": publications,
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
        name: hash_payload(
            [{k: v for k, v in record.items() if k != "retrieved_at"} for record in records]
        )
        for name, records in datasets.items()
    }
    combined_hash = hash_payload(dataset_hashes)
    previous_manifest = read_json(output_dir / "manifest.json", {})
    data_changed = combined_hash != previous_manifest.get("dataset_hash")

    manifest = {
        "schema_version": "1.0",
        "dataset_version": retrieved_at if data_changed else previous_manifest.get("dataset_version", retrieved_at),
        "generated_at": retrieved_at if data_changed else previous_manifest.get("generated_at", retrieved_at),
        "dataset_hash": combined_hash,
        "status": "valid" if not (call_errors or event_errors) else "partial",
        "changed_datasets": changed_datasets,
        "record_counts": {name: len(records) for name, records in datasets.items()},
        "dataset_hashes": dataset_hashes,
        "files": {
            "calls": "calls.json",
            "events": "events.json",
            "publications": "publications.json",
            "changes": "changes-latest.json",
        },
        "source": settings.base_url,
        "errors": call_errors + event_errors,
    }
    write_json(output_dir / "changes-latest.json", all_changes)
    write_json(output_dir / "manifest.json", manifest)

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if manifest["status"] == "partial":
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect public DUT website metadata")
    parser.add_argument("--output", type=Path, default=Path("public"))
    args = parser.parse_args()
    settings = Settings(output_dir=args.output)
    sys.exit(run(settings))


if __name__ == "__main__":
    main()
