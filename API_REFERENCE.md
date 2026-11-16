# API reference

Base path: `/api/v1`. [docs/API_CONTRACT.md](docs/API_CONTRACT.md) defines engine response shapes; this document explains client usage. The parent verified 395 Python tests in 12.05 seconds, including API integration and an offline-docs route regression, plus all 6 real-backend Chromium tests in 25.4 seconds. Independent bounded security reviews reported no vulnerabilities; this is not certification. See [docs/VALIDATION.md](docs/VALIDATION.md). Local `/docs` serves a bundled static OpenAPI viewer without CDN dependencies; `/openapi.json` remains available. The viewer fetches the running server's schema, so it is offline from external services, not independent of the local server. It does not execute dataset requests or store capability tokens. Public/cloud mode disables the `/docs` route.

## Authentication and errors

`POST /datasets/upload` and `POST /datasets/sample/{sample_id}` return a new `dataset_id` and private `token` for **that dataset only**. All subsequent `/datasets/{id}/...` requests require `X-Session-Token: <token>`, including metadata, job polling, downloads and deletion. There is no account or global session token. Never put tokens in URLs. Use an authorized browser `fetch` followed by a Blob download rather than a bare download link.

```json
{"error":{"code":"stale_version","message":"Dataset changed. Refresh and preview again."}}
```

| HTTP status | Meaning |
| --- | --- |
| 400 / 422 | Invalid operation, input or request schema |
| 404 | Unknown resource or missing/invalid dataset capability |
| 409 | Stale revision/preview, missing ingestion, invalid history navigation, or `no_changes` |
| 410 | Dataset expired |
| 413 | Request, dataset, version or storage capacity exceeded |
| 429 | Processing slot busy, session capacity or request-rate limit |
| 500 | Unexpected failure with generic response |

Most success responses use 200; dataset creation uses 201 and ingestion submission 202. Metadata, upload, profile and job responses are validated through Pydantic response models. JSON bodies reject extra top-level fields. Read the specific `error.code`; do not retry all failures blindly.

## Endpoints

`{id}` below is the dataset UUID. Every row with `{id}` requires the matching capability header.

| Method | Path | Input / result |
| --- | --- | --- |
| GET | `/health` | `{status, app_env}`; liveness, not a complete workflow test |
| GET | `/samples` | `{samples:[{id,name,description}]}` |
| POST | `/datasets/upload` | Multipart `file`; metadata, `token`, `inspection` |
| POST | `/datasets/sample/{sample_id}` | Independent dataset/token from synthetic sample |
| POST | `/datasets/{id}/ingest` | Options below; returns `{job_id}` |
| GET | `/datasets/{id}/jobs/{job_id}` | `{job_id,status,error,result}` |
| GET | `/datasets/{id}` | `{dataset_id,filename,active_version,revision,created_at,expires_at}` |
| GET | `/datasets/{id}/preview?offset=0&limit=50` | Paginated rows, columns, total and version; limit 1–200 |
| GET | `/datasets/{id}/profile` | Cached active-version profile |
| GET | `/datasets/{id}/columns/{column}` | One column profile; URL-encode column path |
| GET | `/datasets/{id}/quality` | Cached standard `{issues:[...]}` |
| POST | `/datasets/{id}/quality` | Strict `{domain_rules:{column:{min,max,integer,exclusive_min}}}`; optional explicit constraints, read-only |
| GET | `/datasets/{id}/recommendations` | `{recommendations:[...]}` |
| POST | `/datasets/{id}/anomalies` | Method/columns/optional threshold; findings and warnings |
| POST | `/datasets/{id}/cleaning/preview` | Operation plus expected version/revision; reviewed diff |
| POST | `/datasets/{id}/cleaning/apply` | Preview ID, expected version/revision, `approved:true`; metadata |
| POST | `/datasets/{id}/undo` | Expected version/revision; metadata |
| POST | `/datasets/{id}/redo` | Expected version/revision; metadata |
| POST | `/datasets/{id}/reset` | Expected version/revision; activates baseline 0 |
| POST | `/datasets/{id}/restore` | Target `version`, expected version/revision; metadata |
| GET | `/datasets/{id}/history` | Active version, revision, versions with parent pointers |
| GET | `/datasets/{id}/export?format=csv` | CSV or XLSX attachment |
| GET | `/datasets/{id}/report?format=json` | JSON or HTML attachment; HTML may be printed as PDF |
| GET | `/datasets/{id}/code?language=python` | Python or PostgreSQL reference SQL attachment; not executed |
| GET | `/ai/status` | `{enabled,available,model,reason}` |
| POST | `/datasets/{id}/ai/explain` | Empty object `{}`; `{source,explanation,warnings,reason}` |
| DELETE | `/datasets/{id}` | `{deleted:true}` |

`active_version` is null before successful ingestion. Do not assume revision 0 after ingestion; always read returned metadata. Dataset expiry timestamps and creation timestamps are Unix seconds.

All six attachment formats require successful ingestion. Their `Content-Disposition` names use the sanitized source stem and exported active version, for example `quality_issues-v1.csv`. The filename and contents are selected under the same processing lock. Clients should use that response filename, not a cached UI version. Unicode names use RFC 5987 `filename*` with a safe quoted ASCII fallback. PDF remains a browser print operation on the authorized HTML report.

## Ingestion

```json
{"sheet":null,"header":0,"delimiter":null,"encoding":null}
```

`header:null` means no header; integer header positions are zero-based (0–100). `sheet` selects an Excel sheet by name. An explicit delimiter is one character. Accepted explicit encodings: `utf-8`, `utf-8-sig`, `utf-16`, `cp1252`, `latin-1`. Inspect before choosing options; inspection previews do not prove the full file will fit processing limits.

For CSV, unquoted structurally blank fields become null; explicitly quoted `""` remains an empty string. Literal `NA`, `null`, `?` and leading-zero identifiers remain strings. Quoted fields may contain escaped quotes or line breaks. CSV export uses Python 3.12 `QUOTE_NOTNULL` to retain the null-versus-empty distinction on DataLens reingestion.

Poll statuses `queued`, `running`, `succeeded`, `failed`, `timed_out`. Only `succeeded` publishes baseline metadata in `result`. The timeout is cooperative: a thread that outlives the deadline holds the processing slot until it exits, may still report `running`, and must not publish its timed-out snapshot.

## Review and apply

Illustrative request (replace version/revision with current metadata):

```json
{"operation":{"kind":"trim","column":"name","params":{}},"expected_version":0,"expected_revision":1}
```

The preview returns `preview_id`, `version`, `operation`, affected cell/row counts, rows removed/added, sampled `changes`, and before/after metrics. A displayed change list is not necessarily every changed cell. Review counts and potential data loss before sending:

It also returns `no_changes` and `schema_changed`. When values and dtypes are unchanged, approval is disabled and direct apply returns `409/no_changes` without publishing a snapshot. A dtype-only change is still eligible for review and approval.

```json
{"preview_id":"00000000-0000-0000-0000-000000000000","expected_version":0,"expected_revision":1,"approved":true}
```

Use the real returned preview ID. Apply requires the JSON boolean `true`; truthy numbers and strings are rejected. It does not accept a new operation. The latest preview replaces the previous preview and expires after ten minutes; it is already stale at the exact expiration instant. Navigation or another mutation invalidates it; refresh and preview again on 409.

Undo/redo/reset body:

```json
{"expected_version":1,"expected_revision":2}
```

Restore adds a target `version`. Restoring is explicit branch selection, not deletion of other versions. New changes after undo create a branch and clear redo; old branches remain in history until expiry/deletion.

## Domain-rule quality checks

After ingestion, inspect the profile and decide which business bounds are justified. Submit explicit rules using the dataset's capability header:

```json
{"domain_rules":{"amount":{"min":0,"max":100},"age":{"min":0}}}
```

Send this body to `POST /api/v1/datasets/{id}/quality`. Each column rule requires at least one finite numeric bound or `integer:true`; `min` or `max` may be omitted, and `min` must not exceed `max` when both are supplied. Optional `exclusive_min:true` rejects equality with the supplied minimum and requires `min`. Both flags require strict JSON booleans. Example: `{"unit_price_inr":{"min":0,"exclusive_min":true},"quantity":{"min":1,"integer":true}}`. Checks use actual numeric columns; mixed text requires a separately approved conversion. Unknown fields, invalid bounds or unknown column names return 422.

Review the returned issues against the intended business rules. This request is **read-only**: it does not create a version, change the active version/revision, or authorize cleaning. To correct selected records, separately create a cleaning preview with current metadata, review its changes, then explicitly approve it. `GET /quality` remains the cached standard quality path; submitting domain rules is not a permanent dataset configuration.

## Anomalies and operations

```json
{"method":"mad","columns":["amount"],"threshold":3.5}
```

Methods: `iqr` (default multiplier 1.5), `mad` (default threshold 3.5), `isolation_forest` (threshold ignored). Omit threshold to use a method's default; explicit values must be finite, greater than 0 and at most 20. Select 1–20 columns.

Cleaning kinds: `trim`, `normalize_missing`, `drop_duplicates`, `to_numeric`, `to_date`, `fill_missing`, `drop_column`, `case`, `map_categories`, `handle_infinity`, `outliers`. Parameter semantics and cautions are in [ALGORITHMS.md](ALGORITHMS.md) and the implementation contract. Recommendations are advisory; they do not authorize automatic changes.

For reviewed mixed date formats, use `{"kind":"to_date","column":"order_date","params":{"format":"supported","date_order":"day_first","coerce":false}}`. Omit `date_order` to block ambiguous day/month values; `coerce:true` never bypasses that requirement. Supported conversion emits UTC timestamps. Exact strptime formats remain available.

Column profiles can include `numeric_conversion` with `parseable_count`, `present_count`, `parseable_percentage`, `missing_count`, `invalid_count`, bounded `invalid_examples:[{row_id,value}]`, `invalid_examples_truncated` and `requires_approval:true`. Percentage uses present non-null values as denominator. This is readiness metadata, not an automatic conversion or numeric statistical summary. Category suggestions may include `mappings` containing original/canonical labels, affected counts, similarity, confidence, an exact mapping, explanation and `requires_approval:true`.

## Minimal client commands

Use only non-sensitive sample data. Creation replies include secret tokens: do not paste replies into public logs. Replace placeholders privately rather than sharing actual values.

```bash
curl --fail http://127.0.0.1:8000/api/v1/samples
curl --fail -F 'file=@sample_datasets/example.csv' \
  http://127.0.0.1:8000/api/v1/datasets/upload
curl --fail -H 'X-Session-Token: <dataset-token>' \
  -H 'Content-Type: application/json' -d '{"header":0}' \
  http://127.0.0.1:8000/api/v1/datasets/<dataset-id>/ingest
```

`example.csv` is a placeholder: choose an actual synthetic file in `sample_datasets/`. Avoid placing real secrets into shared shell history; a private client can keep capabilities in memory and add headers programmatically.
