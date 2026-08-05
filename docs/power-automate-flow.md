# Power Automate flow: GitHub public JSON → SharePoint staging

## Assumptions

- The GitHub repository is public.
- The flow can use the HTTP action to GET a public raw GitHub URL.
- SharePoint lists use the internal names in `sharepoint-field-map.csv`.
- Only GitHub-controlled columns are written by the import flow.

## Raw URLs

Replace `<owner>` and `<repo>`:

```text
https://raw.githubusercontent.com/<owner>/<repo>/main/public/manifest.json
https://raw.githubusercontent.com/<owner>/<repo>/main/public/calls.json
https://raw.githubusercontent.com/<owner>/<repo>/main/public/events.json
https://raw.githubusercontent.com/<owner>/<repo>/main/public/publications.json
https://raw.githubusercontent.com/<owner>/<repo>/main/public/changes-latest.json
```

## Main flow

1. **Trigger — Recurrence**
   - Daily, preferably after the GitHub workflow (for example 08:00 Europe/Lisbon).

2. **HTTP — Get manifest**
   - Method: `GET`
   - URI: raw `manifest.json`
   - Add header `Cache-Control: no-cache`.

3. **Parse JSON — Manifest**
   - Generate the schema from `public/manifest.json`.

4. **Get items — DUT_Sync_Control**
   - Filter query: `Title eq 'Main'`
   - Top count: 1.

5. **Condition — source is valid enough to process**
   - Stop and log when manifest status is `partial`, unless the errors are explicitly accepted.

6. **Condition — hash changed**
   - Compare `body('Parse_JSON_-_Manifest')?['dataset_hash']` with the SharePoint `LastDatasetHash`.
   - If equal, terminate as Succeeded: `No material changes`.

7. **Apply to each — changed_datasets**
   - Build raw file URL using the dataset name.
   - GET the file.
   - Parse the relevant JSON array.
   - Apply to each record and invoke the corresponding child flow.

8. **HTTP — Get changes-latest.json**
   - Use high-materiality changes to create an editorial notification or approval task.

9. **Update item — DUT_Sync_Control**
   - LastDatasetHash = manifest.dataset_hash
   - LastDatasetVersion = manifest.dataset_version
   - LastSuccessfulSync = `utcNow()`
   - LastStatus = `valid`
   - Clear LastError.

10. **Configure run-after error branch**
    - Write a record to `DUT_Import_Exceptions`.
    - Update the control row with LastStatus = `failed`.
    - Do not update LastDatasetHash.

## Child flow pattern: upsert one source record

Inputs: dataset name and record object.

1. Select the SharePoint list based on the dataset.
2. `Get items` using a filter on the stable external ID.
3. If no item exists:
   - Create item.
   - Set ReviewStatus = `New`.
   - Set PublicationStatus = `Not selected`.
4. If one item exists:
   - Compare ContentHash.
   - If unchanged, do nothing.
   - If changed, update only GitHub-controlled fields.
   - Preserve LocalSummaryPT, RegionalRelevance, ReviewStatus, PublicationStatus and all other CCDR fields.
5. If more than one item exists:
   - Create an exception record because ExternalSourceID should be unique.

## Useful expressions

Hash from parsed manifest:

```text
body('Parse_JSON_-_Manifest')?['dataset_hash']
```

Changed file URL:

```text
concat(
  'https://raw.githubusercontent.com/<owner>/<repo>/main/public/',
  items('Apply_to_each_-_changed_datasets'),
  '.json'
)
```

Safe date value for a SharePoint Date column:

```text
if(empty(items('Apply_to_each_record')?['opening_date']), null, items('Apply_to_each_record')?['opening_date'])
```

OData filter for ExternalSourceID (escape apostrophes before use if future IDs can contain them):

```text
concat("ExternalSourceID eq '", items('Apply_to_each_record')?['external_id'], "'")
```

## Important operational rule

The import flow must never overwrite CCDR-controlled columns. This should be visible in the mapping of every Create/Update action, not merely documented as an intention.
