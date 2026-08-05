from pathlib import Path

from dut_monitor.parsers import parse_call, parse_event, parse_library

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-08-05T22:30:00Z"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_call() -> None:
    record = parse_call(read("call.html"), "https://dutpartnership.eu/calls/dut-call-2026", NOW)
    assert record["title"] == "DUT Call 2026"
    assert record["opening_date"] == "2026-09-01"
    assert record["stage1_deadline"] == "2026-11-17"
    assert record["stage2_opening"] == "2027-02-01"
    assert record["stage2_deadline"] == "2027-04-15"
    assert record["canonical_url"].endswith("/calls/dut-call-2026")
    assert "call-2026.pdf" in record["documents_json"]


def test_parse_event() -> None:
    record = parse_event(read("event.html"), "https://dutpartnership.eu/events/dut-info-day", NOW)
    assert record["start_date"] == "2026-09-09"
    assert record["location"] == "Online"
    assert record["registration_url"] == "https://example.org/register"
    assert record["mode"] == "online"


def test_parse_library() -> None:
    records = parse_library(read("library.html"), "https://dutpartnership.eu/library", NOW)
    assert len(records) == 2
    assert {item["category"] for item in records} == {
        "DUT Publications",
        "DUT Knowledge Hub Outputs",
    }
