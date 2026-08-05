# Implementation checklist

## GitHub

- [ ] Create a new **public** repository, suggested name `dut-web-monitor`.
- [ ] Upload this package to the repository root.
- [ ] Confirm that Actions are enabled.
- [ ] Run `Update DUT public data` manually once.
- [ ] Inspect the workflow result and `public/manifest.json`.
- [ ] Confirm raw GitHub URLs are accessible without authentication.
- [ ] Add a second repository administrator when the prototype stabilises.

## SharePoint

- [ ] Create `DUT_Sync_Control` and add the `Main` row.
- [ ] Create `DUT_Calls`, `DUT_Events`, `DUT_Publications`, and `DUT_Import_Exceptions`.
- [ ] Use the exact internal names from the field map.
- [ ] Enforce uniqueness and indexing on `ExternalSourceID`.
- [ ] Index `ContentHash` and high-use date/status fields.
- [ ] Add views: New records, Pending review, High-priority changes, Ready to publish, Possibly removed.

## Power Automate

- [ ] Build and test the manifest-only flow.
- [ ] Verify no-change termination using the dataset hash.
- [ ] Build one child upsert flow, starting with `DUT_Publications`.
- [ ] Confirm an update does not erase manually entered local fields.
- [ ] Add calls and events.
- [ ] Add the high-materiality notification route.
- [ ] Add exception logging and run-after handling.

## Validation scenarios

- [ ] First import creates all records.
- [ ] Second import with the same hash creates no versions.
- [ ] A changed deadline is classified as high materiality.
- [ ] A changed title updates source fields but preserves local summary.
- [ ] A temporarily missing source is marked `possibly_removed`, not deleted.
- [ ] A malformed record is logged while other records continue.
