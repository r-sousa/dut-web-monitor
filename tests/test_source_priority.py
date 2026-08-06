import json
from pathlib import Path

from dut_monitor.source_priority import (
    load_legacy_webinars,
    merge_newsletters,
    merge_webinars,
    parse_news,
    parse_primary_newsletters,
)

NOW = "2026-08-06T00:00:00Z"


def test_legacy_webinars_are_backfilled(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "episode_number": 1,
                    "title": "Urban Lunch Talk #1: Test",
                    "page_url": "https://jpi-urbaneurope.eu/event-calendar/test/",
                    "youtube_url": "https://www.youtube.com/watch?v=abcdefghijk",
                    "event_date": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    legacy = load_legacy_webinars(path, NOW)
    primary = [
        {
            "external_id": "p23",
            "content_type": "webinar",
            "episode_number": 23,
            "title": "Urban Lunch Talk #23",
            "source_priority": 1,
        }
    ]
    merged = merge_webinars(primary, legacy)
    assert [item["episode_number"] for item in merged] == [1, 23]
    assert merged[0]["source_role"] == "legacy_primary"


def test_primary_newsletter_archive_is_ranked_first() -> None:
    html = """
    <html><head><link rel='canonical' href='https://dutpartnership.eu/newsletter'></head>
    <body><a href='https://mailchi.mp/dutpartnership/dut-newsletter-march2026?e=x'>March 2026</a></body></html>
    """
    primary = parse_primary_newsletters(html, "https://dutpartnership.eu/newsletter", NOW)
    legacy = [dict(primary[0], source_priority=3, source_role="legacy_regional_backfill")]
    merged = merge_newsletters(primary, legacy)
    assert len(merged) == 1
    assert merged[0]["source_role"] == "primary_european"
    assert "?e=" not in merged[0]["archive_url"]


def test_news_parser_uses_european_page() -> None:
    html = """
    <html><head><link rel='canonical' href='https://dutpartnership.eu/news/example'>
    <meta name='description' content='Example summary'></head>
    <body><main><h1>Example update</h1><div>News June 2026 By Ana Calvo Page content</div>
    <a href="/topics/governance">Governance & policy</a><a href="/transition-pathways/15-minute-city">15-minute City</a></main></body></html>
    """
    record = parse_news(html, "https://dutpartnership.eu/news/example", NOW)
    assert record["published_sort_date"] == "2026-06-01"
    assert record["source_role"] == "primary_european"
    assert "Governance & policy" in record["topics_json"]
