# Power Automate implementation kit — DUT GitHub JSON to SharePoint

This guide implements the first production-safe version of the flow in Microsoft Power Automate cloud flows.

## 1. Deployment model

Use one small manifest-health flow and one dataset flow per SharePoint list:

| Order | Flow name | Dataset | Suggested start |
|---|---|---|---|
| 00 | `DUT 00 - Check manifest` | manifest | 07:50 Europe/Lisbon |
| 10 | `DUT 10 - Sync calls` | calls | 08:00 |
| 20 | `DUT 20 - Sync events` | events | 08:10 |
| 30 | `DUT 30 - Sync news` | news | 08:20 |
| 40 | `DUT 40 - Sync publications` | publications | 08:30 |
| 50 | `DUT 50 - Sync webinars` | webinars | 08:40 |
| 60 | `DUT 60 - Sync newsletters` | newsletters | 08:50 |

The GitHub workflow normally runs at 06:17 UTC. The staggered flows avoid overlapping SharePoint writes and make each dataset independently testable.

Do **not** use one global processed hash. `DUT_Sync_Control` contains one row per dataset and each flow compares its own value from `manifest.dataset_hashes`.

## 2. Raw URLs

```text
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/manifest.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/calls.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/events.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/news.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/publications.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/webinars.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/newsletters.json
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/changes-latest.json
```

## 3. SharePoint preparation

Create the lists and columns from `docs/sharepoint-field-map.csv`.

### 3.1 Internal names

Create each custom column initially using the value in the **Internal Name** column, without spaces. After creation, its visible display name may be changed. Power Automate OData filters must use the internal name.

### 3.2 Indexes and uniqueness

For every content list:

1. Index `ExternalSourceID`.
2. Enable **Enforce unique values** on `ExternalSourceID`.
3. Index `ContentHash`.
4. Create a view named `PA_Sync` containing only the columns used by the flow.

### 3.3 Control rows

Create these seven rows in `DUT_Sync_Control`:

```text
manifest
calls
events
news
publications
webinars
newsletters
```

Leave `LastDatasetHash` empty before the first run.

### 3.4 Choice values

Use the exact values in the field map. Important examples:

```text
SourceStatus: active | possibly_removed | archived
ReviewStatus: New | Pending | Approved | Rejected | Clarification
PublicationStatus: Not selected | Ready | Published | Archived
EventMode: online | on-site | hybrid | unspecified
SourceRole: primary_european | secondary_manual | legacy_primary | legacy_regional_backfill
```

## 4. Flow `DUT 00 - Check manifest`

### Trigger

Create a **Scheduled cloud flow**.

- Frequency: Day
- Interval: 1
- Time zone: `(UTC+00:00) Dublin, Edinburgh, Lisbon, London`
- Start time: 07:50 local
- Trigger concurrency: 1

### Actions

#### 1. HTTP — `HTTP_Get_manifest`

- Method: `GET`
- URI:

```text
https://raw.githubusercontent.com/r-sousa/dut-web-monitor/main/public/manifest.json
```

- Headers:

```text
Cache-Control    no-cache
Accept           application/json
```

#### 2. Parse JSON — `Parse_JSON_Manifest`

Content:

```text
body('HTTP_Get_manifest')
```

Schema: paste `docs/power-automate-schemas/manifest.parse-json-schema.json`.

If the HTTP action returns a string in your environment, use:

```text
json(body('HTTP_Get_manifest'))
```

Do not use `json()` when the body is already an object.

#### 3. Get items — `Get_control_manifest`

- Site Address: your DUT SharePoint site
- List Name: `DUT_Sync_Control`
- Filter Query:

```text
Title eq 'manifest'
```

- Top Count: `1`
- Limit Columns by View: `PA_Sync`, when available

#### 4. Condition — `Manifest_is_valid`

Expression:

```text
and(
  equals(body('Parse_JSON_Manifest')?['status'], 'valid'),
  equals(length(body('Parse_JSON_Manifest')?['errors']), 0)
)
```

If **No**:

- Update the `manifest` control row:
  - `LastStatus` = `partial`
  - `LastError` =

```text
string(body('Parse_JSON_Manifest')?['errors'])
```

- Create an item in `DUT_Import_Exceptions`.
- Terminate as Failed.

If **Yes**:

- Update the `manifest` control row:
  - `LastDatasetHash` = `dataset_hash`
  - `LastDatasetVersion` = `dataset_version`
  - `LastSuccessfulSync` = `utcNow()`
  - `LastStatus` = `valid`
  - clear `LastError`

This flow does not write content records.

## 5. Flow `DUT 10 - Sync calls`

Build this flow completely before cloning it.

### Trigger

Scheduled cloud flow, daily at 08:00 Europe/Lisbon. Set trigger concurrency to 1.

### Variables

Create:

| Name | Type | Initial value |
|---|---|---|
| `varDataset` | String | `calls` |
| `varDatasetURL` | String | calls raw URL |
| `varControlID` | Integer | `0` |
| `varDatasetHash` | String | empty |

### Scope `TRY_Calls`

Put all normal actions inside this scope.

#### 1. HTTP — `HTTP_Get_manifest`

Same configuration as the health flow.

#### 2. Parse JSON — `Parse_JSON_Manifest`

Use the manifest schema.

#### 3. Condition — `Manifest_valid`

Use the same validity expression. If false, terminate as Failed. Do not process a partial manifest.

#### 4. Compose — `Compose_Calls_hash`

```text
body('Parse_JSON_Manifest')?['dataset_hashes']?['calls']
```

Set `varDatasetHash` to the Compose output.

#### 5. Get items — `Get_control_calls`

- List: `DUT_Sync_Control`
- Filter Query:

```text
Title eq 'calls'
```

- Top Count: `1`

#### 6. Condition — `Control_row_exists`

```text
greater(length(body('Get_control_calls')?['value']), 0)
```

If No, create a control row with `Title = calls`. Set `varControlID` from the new item ID.

If Yes, set `varControlID`:

```text
first(body('Get_control_calls')?['value'])?['ID']
```

#### 7. Condition — `Calls_hash_changed`

For an existing control row:

```text
not(
  equals(
    first(body('Get_control_calls')?['value'])?['LastDatasetHash'],
    variables('varDatasetHash')
  )
)
```

For a newly created control row, continue directly.

If No, terminate as Succeeded with message `No calls changes`.

#### 8. HTTP — `HTTP_Get_calls`

- Method: GET
- URI: `variables('varDatasetURL')`
- Headers: same as manifest.

#### 9. Parse JSON — `Parse_JSON_Calls`

Content:

```text
body('HTTP_Get_calls')
```

Schema: `docs/power-automate-schemas/calls.parse-json-schema.json`.

#### 10. Apply to each — `For_each_call`

Input:

```text
body('Parse_JSON_Calls')
```

Keep concurrency **off** initially. SharePoint writes are then sequential.

Inside the loop:

##### 10.1 Compose — `Compose_Escaped_external_id`

```text
replace(item()?['external_id'],'''','''''')
```

##### 10.2 Get items — `Get_existing_call`

- List: `DUT_Calls`
- Filter Query, entered as an expression:

```text
concat(
  'ExternalSourceID eq ''',
  outputs('Compose_Escaped_external_id'),
  ''''
)
```

- Top Count: `2`
- Limit Columns by View: `PA_Sync`

Top Count 2 deliberately detects accidental duplicate IDs.

##### 10.3 Switch by match count

Use a Condition or Switch based on:

```text
length(body('Get_existing_call')?['value'])
```

###### Count = 0 — Create item

Map only source-controlled fields:

| SharePoint column | Value |
|---|---|
| Title | `item()?['title']` |
| Subtitle | `item()?['subtitle']` |
| SourceDescription | `item()?['source_description']` |
| ParticipatingCountriesText | `item()?['participating_countries_text']` |
| RetrievedAt | `item()?['retrieved_at']` |
| ExternalSourceID | `item()?['external_id']` |
| SourceURL | `item()?['canonical_url']` |
| SourceStatus | `item()?['source_status']` |
| ContentHash | `item()?['content_hash']` |
| CallStatus | `item()?['status']` |
| OpeningDate | safe-date expression below |
| Stage1Deadline | safe-date expression below |
| Stage2Opening | safe-date expression below |
| Stage2Deadline | safe-date expression below |
| TopicsJSON | `item()?['topics_json']` |
| DocumentsJSON | `item()?['documents_json']` |
| ReviewStatus | `New` |
| PublicationStatus | `Not selected` |

Safe date pattern:

```text
if(empty(item()?['opening_date']), null, item()?['opening_date'])
```

Repeat with each date property.

###### Count = 1 — Compare hash

Condition:

```text
not(
  equals(
    first(body('Get_existing_call')?['value'])?['ContentHash'],
    item()?['content_hash']
  )
)
```

If false, do nothing.

If true, use **Update item**. Map:

- ID:

```text
first(body('Get_existing_call')?['value'])?['ID']
```

- all source-controlled fields listed above;
- every required SharePoint field.

Do **not** map or overwrite:

```text
LocalSummaryPT
NationalFundingInformation
ReviewStatus
PublicationStatus
EditorialNotes
ReviewedBy
ReviewedAt
```

Because `ReviewStatus` is required, preserve its current value in Update item:

```text
first(body('Get_existing_call')?['value'])?['ReviewStatus']?['Value']
```

Depending on the connector output, a Choice column may already be returned as plain text. In that case use:

```text
first(body('Get_existing_call')?['value'])?['ReviewStatus']
```

Use the same approach for `PublicationStatus`.

###### Count > 1 — Log exception

Create item in `DUT_Import_Exceptions`:

- Title = external ID
- Dataset = calls
- ErrorTime = `utcNow()`
- ErrorDetail = `Duplicate ExternalSourceID in DUT_Calls`
- Payload = `string(item())`

Then terminate the flow as Failed. Do not update the dataset hash.

#### 11. Update item — `Update_control_calls_success`

Only after the complete loop succeeds:

- ID = `variables('varControlID')`
- Title = `calls`
- LastDatasetHash = `variables('varDatasetHash')`
- LastDatasetVersion = manifest `dataset_version`
- LastSuccessfulSync = `utcNow()`
- LastStatus = `valid`
- LastRecordCount = manifest `record_counts.calls`
- clear LastError

## 6. Scope `CATCH_Calls`

Add a second scope after `TRY_Calls`.

Use **Configure run after** so it runs when `TRY_Calls`:

- has failed;
- has timed out;
- is skipped.

Actions:

1. Create an item in `DUT_Import_Exceptions`.
2. Update the calls control row when `varControlID` is greater than zero:
   - LastStatus = failed
   - LastError =

```text
string(result('TRY_Calls'))
```

3. Terminate as Failed.

Never update `LastDatasetHash` in the catch scope.

## 7. First validation cycle

1. Confirm `DUT_Sync_Control` has a `calls` row with a blank hash.
2. Run `DUT 10 - Sync calls` manually.
3. Confirm exactly five `DUT_Calls` items were created.
4. Confirm the control row stores `manifest.dataset_hashes.calls`.
5. Run the flow again.
6. Confirm it exits through `No calls changes` without SharePoint writes.
7. Temporarily edit one calls item locally in a CCDR-controlled field.
8. Clear only the calls control hash and rerun.
9. Confirm the local field was preserved.
10. Restore the control hash through the successful run.

## 8. Clone mapping for the remaining flows

Clone the calls flow and change only the dataset name, raw URL, JSON schema, SharePoint list and field mappings.

| Dataset | Control title | List | Parse schema | Expected baseline |
|---|---|---|---|---:|
| events | events | DUT_Events | events | 95 |
| news | news | DUT_News | news | 82 |
| publications | publications | DUT_Publications | publications | 17 |
| webinars | webinars | DUT_Webinars | webinars | 46 |
| newsletters | newsletters | DUT_Newsletters | newsletters | 15 |

The manifest count is the source of truth; the numbers above are only the current baseline.

### Dataset-specific preservation rule

All Update item actions must preserve the CCDR-controlled fields. New items receive `ReviewStatus = New` and `PublicationStatus = Not selected`.

### Provenance mapping

For news, webinars and newsletters, map:

```text
SourcePriority
SourceRole
SourceName
```

For current European records, `SourceRole` is normally `primary_european`. Legacy Urban Lunch Talks use `legacy_primary`; legacy newsletter issues use `legacy_regional_backfill`.

## 9. Performance and limits

- Use `ExternalSourceID` as an indexed, unique lookup key.
- Use Filter Query and Top Count 2 rather than retrieving the whole list.
- Keep Apply to each concurrency off for the first deployment.
- The SharePoint `Get items` action defaults to a limited page size, but the filtered query should return at most one item.
- Enable pagination only where a flow intentionally reads a whole list.
- Stagger the dataset flows to reduce simultaneous connector requests.

## 10. Publication workflow — separate concern

The import flows populate staging lists. They must not automatically publish all imported records.

A later flow can trigger when `PublicationStatus` changes to `Ready` and generate an approved public JSON export or send the record to the October CMS integration. Keep source ingestion and publication approval as separate flows.
