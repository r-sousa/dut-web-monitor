# DUT web monitor

This repository monitors public Driving Urban Transitions content and publishes simple JSON files for ingestion by Microsoft Power Automate and SharePoint.

## Dataset scope

- DUT Calls
- DUT Events
- DUT News and stories
- DUT Library publications
- Urban Lunch Talk webinars, including the JPI Urban Europe legacy series #1–#22
- DUT newsletter archive records from 2022 onward

Projects and organisations are intentionally deferred until the GitHub → Power Automate → SharePoint pipeline has been validated.

## Data flow

```text
European DUT website + frozen official legacy sources
        ↓
GitHub Actions (daily collection, validation and change detection)
        ↓
public/*.json on raw.githubusercontent.com
        ↓
Power Automate HTTP GET
        ↓
SharePoint staging and editorial approval
        ↓
CCDR NORTE DUT pages
```

GitHub has no Microsoft credentials and no access to the CCDR NORTE environment.

## Source hierarchy

The process uses an explicit, non-circular source hierarchy:

1. **European DUT sources** are authoritative for current news, events, webinars and any newsletter archives exposed by the European website.
2. **Controlled manual JSON files** under `data/manual/` are the secondary layer for exceptional regional additions not yet exposed by the European source.
3. **Frozen legacy datasets** under `data/legacy/` preserve:
   - Urban Lunch Talks #1–#22 from the official JPI Urban Europe predecessor series;
   - the newsletter archive already assembled for the regional DUT page, covering 2022 to February 2026.

The scheduled process does not scrape the regional DUT output pages. Those pages may therefore be generated from the approved database without creating a circular dependency.

## Repository output

- `public/manifest.json`: version, source hierarchy, dataset hashes and counts.
- `public/calls.json`: call records.
- `public/events.json`: event records.
- `public/news.json`: European DUT news and stories, plus controlled manual additions.
- `public/publications.json`: library publication records.
- `public/webinars.json`: complete Urban Lunch Talk series available to the monitor.
- `public/newsletters.json`: newsletter archive records with explicit provenance.
- `public/changes-latest.json`: field-level changes for editorial routing.

Power Automate test payloads are under `examples/power-automate/`; they are deliberately kept outside `public/` so they cannot be mistaken for live records.

## Manual secondary layer

- `data/manual/news.json`
- `data/manual/newsletters.json`

These files are reviewed inputs, not generated regional webpages. European records win whenever the same canonical URL is present in both layers.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest -q
python -m dut_monitor.runner --output public
```

## GitHub setup

Run **Update DUT public data** manually for validation. The workflow subsequently runs daily at 06:17 UTC and commits only material source-data changes.

## Power Automate and SharePoint

See:

- `docs/sharepoint-field-map.csv`
- `docs/power-automate-flow.md`
- `docs/power-automate-schemas/`
- `docs/implementation-checklist.md`

## Design principles

- Prefer European sitemaps and structured metadata; use HTML selectors only as fallback.
- Collect public metadata and links rather than copying complete source pages.
- Preserve canonical URLs, provenance, source priority and source role.
- Use stable external IDs and content hashes.
- Do not automatically delete missing records.
- Never overwrite CCDR-controlled editorial fields.
- Leave uncertain dates empty instead of inferring them from unrelated page content.
- Keep request frequency conservative and use an identifying user agent.
