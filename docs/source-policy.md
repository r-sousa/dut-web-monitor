# DUT source and provenance policy

## Current information

Current calls, news, events, publications and Urban Lunch Talks are collected from the European DUT website. Records are marked `primary_european` and have source priority 1.

## Manual regional additions

Exceptional additions can be entered in the reviewed files under `data/manual/`. They are marked `secondary_manual` and have priority 2. They must not reproduce records already available from the European source.

## Legacy backfill

Urban Lunch Talks #1–#22 are retained from the official JPI Urban Europe predecessor series and are marked `legacy_primary`.

Newsletter archive records assembled before the automated process are frozen once from the existing public dataset. They are marked `legacy_regional_backfill`, have priority 3 and are no longer refreshed by scraping the regional page.

## Publication pages

Regional DUT webpages are downstream outputs. They should consume approved SharePoint records and must not become inputs to the scheduled scraper.
