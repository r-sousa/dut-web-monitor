from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import canonicalise_url, hash_payload, normalise_space, read_json, stable_external_id


def load_legacy_webinars(path: Path, retrieved_at: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in read_json(path, []):
        raw_page_url = str(item.get("page_url") or "").strip()
        title = normalise_space(str(item.get("title") or ""))
        episode_number = item.get("episode_number")
        if not title or not raw_page_url or not isinstance(episode_number, int):
            continue
        page_url = canonicalise_url("https://jpi-urbaneurope.eu", raw_page_url)
        recording_url = str(item.get("youtube_url") or "") or None
        payload = {"episode_number": episode_number, "title": title, "canonical_url": page_url, "recording_url": recording_url, "source_role": "legacy_primary"}
        records.append(
            {
                "external_id": stable_external_id("webinar", page_url),
                "content_type": "webinar",
                "series": "Urban Lunch Talks",
                "episode_number": episode_number,
                "title": title,
                "canonical_url": page_url,
                "source_event_id": None,
                "event_date": item.get("event_date"),
                "end_date": None,
                "date_text": None,
                "time_text": None,
                "recording_url": recording_url,
                "recording_status": "available" if recording_url else "not_found",
                "registration_url": None,
                "speakers_json": "[]",
                "moderator": None,
                "description_excerpt": "Legacy Urban Lunch Talk from the JPI Urban Europe series continued by DUT.",
                "source_priority": 1,
                "source_role": "legacy_primary",
                "source_name": "JPI Urban Europe",
                "source_status": "active",
                "retrieved_at": retrieved_at,
                "content_hash": hash_payload(payload),
            }
        )
    return records


def annotate_primary_webinars(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated = []
    for item in records:
        copy = dict(item)
        copy.update({"source_priority": 1, "source_role": "primary_european", "source_name": "DUT Partnership"})
        copy["content_hash"] = hash_payload({key: value for key, value in copy.items() if key not in {"retrieved_at", "content_hash"}})
        annotated.append(copy)
    return annotated


def merge_webinars(primary: list[dict[str, Any]], legacy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_episode: dict[int | str, dict[str, Any]] = {}
    for item in [*legacy, *primary]:
        key: int | str = item.get("episode_number") or item["external_id"]
        current = by_episode.get(key)
        if current is None or item.get("source_priority", 99) <= current.get("source_priority", 99):
            by_episode[key] = item
    return sorted(by_episode.values(), key=lambda item: (item.get("episode_number") is None, item.get("episode_number") or 9999, item["title"]))
