# DUT web monitor

This repository monitors selected public content on the European Driving Urban Transitions website and publishes simple JSON files for ingestion by Microsoft Power Automate and SharePoint.

## Scope of the first version

- DUT Calls
- DUT Events
- DUT Library publications

Projects and organisations are intentionally deferred until the basic GitHub → Power Automate → SharePoint pipeline has been validated.

## Data flow

```text
European DUT website
        ↓
GitHub Actions (daily collection, validation and change detection)
        ↓
public/*.json on raw.githubusercontent.com
        ↓
Power Automate HTTP GET
        ↓
SharePoint staging and editorial approval
```

GitHub has no Microsoft credentials and no access to the CCDR NORTE environment.

## Repository output

- `public/manifest.json`: version, dataset hash, changed datasets and counts.
- `public/calls.json`: flat call records.
- `public/events.json`: flat event records.
- `public/publications.json`: flat publication records.
- `public/changes-latest.json`: field-level changes for editorial routing.

Power Automate test payloads are under `examples/power-automate/`; they are deliberately kept outside `public/` so they cannot be mistaken for live records.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
pytest -q
python -m dut_monitor.runner --output public
```

## GitHub setup

1. Create a public repository.
2. Upload the contents of this package to its root.
3. Enable GitHub Actions.
4. Run **Update DUT public data** manually.
5. Verify the JSON files under `public/`.

The workflow then runs daily at 06:17 UTC and commits only material source-data changes.

## Power Automate and SharePoint

See:

- `docs/sharepoint-field-map.csv`
- `docs/power-automate-flow.md`
- `docs/power-automate-schemas/`
- `docs/implementation-checklist.md`

## Design principles

- Prefer sitemaps and structured metadata; use HTML selectors only as fallback.
- Collect public metadata and links rather than copying complete source pages.
- Preserve source attribution and canonical URLs.
- Use stable external IDs and content hashes.
- Do not automatically delete missing records.
- Never overwrite CCDR-controlled editorial fields.
- Keep request frequency conservative and use an identifying user agent.

## Current limitations

The parsers are covered by representative offline fixtures, but their first live GitHub run is intentionally treated as a validation run. The European site may expose additional structured fields or markup variants that require parser adjustment after the first collected output is inspected.
