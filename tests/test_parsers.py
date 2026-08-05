import json
from pathlib import Path

from dut_monitor.parsers import (
    is_webinar_title,
    parse_call,
    parse_event,
    parse_library,
    parse_regional_newsletters,
    parse_webinar,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-08-05T22:30:00Z"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_call() -> None:
    record = parse_call(read("call.html"), "https://dutpartnership.eu/calls/dut-call-2026", NOW)
    assert record["title"] == "DUT Call 2026"
    assert record["status"] == "forthcoming"
    assert record["opening_date"] == "2026-09-01"
    assert record["stage1_deadline"] == "2026-11-17"
    assert record["stage2_opening"] == "2027-02-01"
    assert record["stage2_deadline"] == "2027-04-15"
    assert json.loads(record["topics_json"]) == [
        "Adaptive reuse of existing urban structures and spaces",
        "Align ambitions for mobility transitions across sectors",
    ]
    assert record["canonical_url"].endswith("/calls/dut-call-2026")
    assert "call-2026.pdf" in record["documents_json"]


def test_historical_call_with_results_is_not_open() -> None:
    html = """
    <html><body><main><h1>DUT Call 2024</h1><p>A funding opportunity.</p>
    <h2>Documents</h2><a href='/results.pdf'>Projects suggested for funding</a>
    </main></body></html>
    """
    record = parse_call(html, "https://dutpartnership.eu/calls/dut-call-2024", NOW)
    assert record["status"] == "results"


def test_parse_event() -> None:
    record = parse_event(read("event.html"), "https://dutpartnership.eu/events/dut-info-day", NOW)
    assert record["start_date"] == "2026-09-09"
    assert record["location"] == "Online"
    assert record["registration_url"] == "https://example.org/register"
    assert record["mode"] == "online"


def test_event_does_not_use_unrelated_future_year() -> None:
    html = """
    <html><body><main><h1>AGORA Strategic Dialogue</h1>
    <div>Online</div><div>Date</div><div>12 Feb</div><div>Time</div><div>13.00 – 16.00</div>
    <p>Thriving urban areas in 2040: navigating crises and uncertainty.</p>
    </main></body></html>
    """
    record = parse_event(html, "https://dutpartnership.eu/events/agora-strategic-dialogue", NOW)
    assert record["start_date"] is None
    assert record["mode"] == "online"


def test_event_range_and_hybrid_mode() -> None:
    html = """
    <html><body><main><h1>DUT City Panel 2026</h1>
    <div>Hybrid</div><div>Date</div><div>6 Oct – 7 Oct 2026</div>
    <div>Location</div><div>Szeged</div>
    </main></body></html>
    """
    record = parse_event(html, "https://dutpartnership.eu/events/dut-city-panel", NOW)
    assert record["start_date"] == "2026-10-06"
    assert record["end_date"] == "2026-10-07"
    assert record["mode"] == "hybrid"


def test_parse_library() -> None:
    records = parse_library(read("library.html"), "https://dutpartnership.eu/library", NOW)
    assert len(records) == 2
    assert {item["category"] for item in records} == {
        "DUT Publications",
        "DUT Knowledge Hub Outputs",
    }


def test_parse_webinar() -> None:
    record = parse_webinar(
        read("webinar.html"),
        "https://dutpartnership.eu/events/urban-lunch-talk-45-energy-communities",
        NOW,
    )
    assert is_webinar_title(record["title"])
    assert record["episode_number"] == 45
    assert record["event_date"] == "2026-03-04"
    assert record["recording_url"] == "https://www.youtube.com/watch?v=AbCdEf12345"
    assert record["recording_status"] == "available"
    assert json.loads(record["speakers_json"]) == [
        "Adela Bara, Bucharest Academy",
        "Chris Vrettos, REScoop",
    ]
    assert record["moderator"] == "Ana Calvo, DUT Partnership"


def test_parse_regional_newsletters() -> None:
    records = parse_regional_newsletters(
        read("newsletters.html"),
        "https://www.ccdr-n.pt/pagina/outra-documentacao-relevante-dut",
        NOW,
    )
    assert len(records) == 3
    assert records[0]["issue_label"] == "Fevereiro 2026"
    assert records[0]["issue_sort_date"] == "2026-02-01"
    assert records[-1]["issue_period"] == "season"
    assert all("e=" not in item["archive_url"] for item in records)
