from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://dutpartnership.eu"
    calls_index: str = "/dut-calls"
    events_index: str = "/events"
    news_index: str = "/news"
    library_index: str = "/library"
    webinars_index: str = "/urban-lunch-talk-webinars"
    newsletter_primary_path: str = "/newsletter"
    legacy_webinars_path: Path = field(
        default_factory=lambda: Path("data/legacy/urban_lunch_talks_1_22.json")
    )
    legacy_newsletters_path: Path = field(
        default_factory=lambda: Path("data/legacy/newsletters_2022_2026.json")
    )
    manual_newsletters_path: Path = field(
        default_factory=lambda: Path("data/manual/newsletters.json")
    )
    manual_news_path: Path = field(default_factory=lambda: Path("data/manual/news.json"))
    sitemap_paths: tuple[str, ...] = ("/sitemap.xml", "/sitemap_index.xml")
    user_agent: str = (
        "CCDR-NORTE-DUT-Monitor/0.2 "
        "(+https://www.ccdr-n.pt/pagina/driving-urban-transitions-dut; "
        "public-metadata-monitor)"
    )
    request_timeout_seconds: int = 30
    max_retries: int = 3
    delay_seconds: float = 0.75
    output_dir: Path = field(default_factory=lambda: Path("public"))
    max_detail_pages_per_type: int = 500


SETTINGS = Settings()
