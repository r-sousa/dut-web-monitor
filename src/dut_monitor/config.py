from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://dutpartnership.eu"
    calls_index: str = "/dut-calls"
    events_index: str = "/events"
    library_index: str = "/library"
    webinars_index: str = "/urban-lunch-talk-webinars"
    regional_newsletters_url: str = (
        "https://www.ccdr-n.pt/pagina/outra-documentacao-relevante-dut"
    )
    sitemap_paths: tuple[str, ...] = ("/sitemap.xml", "/sitemap_index.xml")
    user_agent: str = (
        "CCDR-NORTE-DUT-Monitor/0.1 "
        "(+https://www.ccdr-n.pt/pagina/driving-urban-transitions-dut; "
        "public-metadata-monitor)"
    )
    request_timeout_seconds: int = 30
    max_retries: int = 3
    delay_seconds: float = 0.75
    output_dir: Path = field(default_factory=lambda: Path("public"))
    max_detail_pages_per_type: int = 500


SETTINGS = Settings()
