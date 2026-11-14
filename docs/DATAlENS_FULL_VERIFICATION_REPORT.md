# DataLens — full system verification

Verification date: **2026-11-14 (UTC)**. Base commit: `ce483876aef0a3023dd55982d85e68d37dea282b`, plus the local uncommitted repairs and tests described below. This is an execution record, not a production certification. Historical release and export-only counts in [VALIDATION.md](VALIDATION.md) are separate runs, not additive.

## 1. Overall result and counting

The final regression passed **all 653 automated cases**: **619 Python tests** in **61.95 seconds** (one dependency deprecation warning) and **34 Chromium workflows** in **173.349 seconds**. Both suites have zero final failures or skips; Chromium also has zero flaky results. The completed [test matrix](DATAlENS_TEST_MATRIX.md) reconciles every collected test identity with its expected behavior and actual execution result.

| Scope | Defined | Executed | Passed | Failed | Blocked | Not tested |
|---|---:|---:|---:|---:|---:|---:|
| Python | 619 | 619 | 619 | 0 | 0 | 0 |
| Chromium / frontend | 34 | 34 | 34 | 0 | 0 | 0 |
| External / instrumentation gaps | 11 | 0 | 0 | 0 | 4 | 7 |
| **Total** | **664** | **653** | **653** | **0** | **4** | **7** |

Blocked and untested cases EXT-01–EXT-11 have explicit reasons in the matrix and [current limitations](DATAlENS_KNOWN_LIMITATIONS.md). All runnable defined cases executed; the eleven gaps are not counted as passes.

The matrix counts each collected parametrized Python case and each Chromium workflow once. Repeated targeted runs, assertions inside a test, and build/diagnostic gates are not additional unique tests. Explicit external/unexecuted scenarios are listed separately rather than silently counted as passed. Feature-level **PARTIAL** means tested aspects succeeded but a listed boundary remains; it is not another executed test.

No existing tests were removed or weakened. Relative to the completed export repair (402 Python / 12 browser), this verification adds **217 Python cases and 22 browser workflows**. The initial integration baseline was 395 / 6. No claim of 100% code coverage, universal correctness, or absence of all vulnerabilities is made.

## 2. Scope, architecture and isolation

Inspected the application modules, models, routes, SQLite/store/job lifecycle, deterministic engines, AI gateway, frontend modules/styles/build pipeline, all existing tests, bundled samples, scripts, dependency manifests/locks, container configuration, and project documentation. Generated assets and historical documentation were reviewed as supporting artifacts, not mistaken for current test results. Private environment secrets and private source documents were not read for this verification.

The architecture remains **FastAPI → one processing gate → pandas engines → SQLite metadata plus immutable Parquet snapshots and preserved uploaded bytes**. Frontend remains the existing vanilla JavaScript / Tailwind / ECharts workbench. No database migration, replacement framework, UI redesign, dependency installation, or deployment was introduced.

- Python: existing Python 3.12.3 virtual environment. Node 22.23.4 / npm 10.9.9. Browser: configured Chromium, one worker.
- Unit/API tests use isolated temporary stores. Test collection now also isolates the eager ASGI import from the real environment/store.
- Browser tests use the real local backend on port 8765, synthetic input and a private test storage root; core processing is not mocked. Intentional missing-route/error cases are explicitly isolated tests.
- The restart workflow owns a separate Uvicorn child, ephemeral port and storage directory. It stops/restarts only that child, then removes only its own store.
- The user's existing server and real dataset store were not restarted, cleaned, reset or migrated. Samples were not regenerated.
- No provider request, secret change, commit, push or deployment occurred in this verification.

## 3. Implemented feature inventory

“Existing” identifies pre-audit coverage; “Added / gap” identifies the expanded checks or remaining boundaries. Detailed parametrized expectations and actual outcomes are in the matrix.

| Feature | Expected behavior | Backend | Frontend | Existing coverage | Added / gap |
|---|---|---|---|---|---|
| CSV ingestion | Validate input; inspect delimiter/encoding/header; preserve source bytes and stable IDs | [ingestion.py](../backend/ingestion.py), [main.py](../backend/main.py) | Upload/inspection in [app.js](../frontend/app.js) | Ingestion/API tests and real upload | Header/no-header/custom/duplicate choices, exact parsed values, malformed/limit cases |
| XLSX ingestion | Select worksheet/header; preserve text IDs and untrusted formulas as text | [ingestion.py](../backend/ingestion.py) | Workbook sheet chooser | Engine/API and browser workbook workflow | All bundled sheets, mixed scalar/format tradeoffs, actual exported cell types |
| Upload rejection and limits | Reject empty/unsupported/malformed/oversize/overexpanded inputs without partial publication | [config.py](../backend/config.py), [ingestion.py](../backend/ingestion.py), [main.py](../backend/main.py) | Actionable errors | Boundary, archive and API tests | Public/body/session/storage limits, rollback and timeout paths; no production-capacity claim |
| Built-in samples | Load known immutable synthetic sources | [main.py](../backend/main.py), [sample_datasets](../sample_datasets) | Sample cards | Sample/engine/browser tests | Every sample/sheet inspected; all five source hashes unchanged |
| Dataset sessions/switching | Capability per dataset; tab-local selection; explicit switch/cancel | [store.py](../backend/store.py), [main.py](../backend/main.py) | [api.js](../frontend/api.js), [app.js](../frontend/app.js) | Token, deletion and reload cases | Independent tab, cancelled/accepted switch, all endpoint authorization checks |
| Overview and inventory | Exact rows/columns/cells/missing percentage/duplicates/constants/types | [analysis.py](../backend/analysis.py) | Overview metrics and inventory | Engine/API/browser profile cases | Hand-computed fixtures, empty/all-null/mixed/constant cases |
| Numeric profiling | Defined statistics, quantiles, histograms, infinity treatment and JSON-safe values | [analysis.py](../backend/analysis.py) | Column explorer and [charts.js](../frontend/charts.js) | Analysis tests | Exact expected numeric results and histogram counts/edges |
| Categorical profiling | Count only observed labels; stable first-observed tie ordering | [analysis.py](../backend/analysis.py) | Frequencies/column explorer | Existing categorical cases | Ordered/unordered unused-category regression fixed; no zero-count invented labels |
| Date and semantic profiling | Date bounds and conservative semantic suggestions; no automatic conversion | [analysis.py](../backend/analysis.py) | Column detail | Date/type tests | Known bounds/types; phone/identifier recommendation improvements remain deferred |
| Correlation | Bounded numeric correlation with defined missing/constant behavior | [analysis.py](../backend/analysis.py) | Heatmap in [charts.js](../frontend/charts.js) | Analysis tests | Exact matrices and edge fixtures; not exhaustive dual Pearson/Spearman support |
| Preview/pagination | Stable source IDs; correct page boundaries; internal IDs not data columns | [store.py](../backend/store.py), [main.py](../backend/main.py) | Dataset/affected-row explorer | API/engine tests | Real 57-row next/previous UI checks verify boundary IDs 0/25/50, page sizes 25/25/7 and final-page control state |
| Default quality checks | Deterministic findings identify expected rows/counts without changing data | [analysis.py](../backend/analysis.py) | Quality list | Analysis/API/browser tests | 17 default categories plus explicit domain category, exact positive/negative fixtures |
| Quality filters/explorer | Combine severity/category/column filters; inspect returned stable IDs | [main.py](../backend/main.py) | Quality controls in [app.js](../frontend/app.js) | Basic exploration | Combined real-browser filters and exact whitespace row IDs |
| Domain bounds | Explicit finite min/max rules; no stored snapshot mutation | [models.py](../backend/models.py), [analysis.py](../backend/analysis.py) | Domain rule form | API and existing browser test | Boundary/unknown-column rejection and repeated nonmutation checks |
| IQR/MAD anomalies | Exact reviewed thresholds and IDs; never automatically remove | [analysis.py](../backend/analysis.py) | Method/feature chooser, scatter | Engine/API tests | Strict threshold boundaries, bounded examples and real UI method execution |
| Isolation Forest | Opt-in deterministic bounded multivariate analysis | [analysis.py](../backend/analysis.py) | Anomaly form | Engine/API cases | Real execution and UI with two features; no real-world accuracy claim |
| Recommendations | Executable proposals with tradeoffs and mandatory approval | [analysis.py](../backend/analysis.py) | Suggested actions | Engine/API tests | Returned recommendation operations validated; semantic appropriateness remains heuristic |
| Cleaning preview | Validate exact operation; show counts/diff; no source/active mutation | [cleaning.py](../backend/cleaning.py), [store.py](../backend/store.py) | Cleaning Studio | All operation unit/API basics | Every operation UI lifecycle and detailed value/ID/count assertions |
| Explicit approval | Apply only latest reviewed operation and matching revision; strict boolean | [models.py](../backend/models.py), [store.py](../backend/store.py) | Checkbox and confirmation dialog | Unapproved/stale tests | Numeric/string truthy approvals rejected; exact expiry instant rejected |
| All 11 transformations | Deep-copy transformations with stable IDs and immutable original | [cleaning.py](../backend/cleaning.py) | Operation-specific controls | Existing engine/API transformations | Variants, null/empty/precision/overflow, chained pipeline, Python replay; see operation table |
| Version history/undo/redo/reset/restore | Immutable branches, active pointer, monotonic revision; reset selects v0 | [store.py](../backend/store.py) | History/actions | API/store and browser workflow | Every operation lifecycle, branch/redo invalidation, original/v0 byte comparison |
| Session retention/recovery | Fixed lifetime; valid expired capability 410, deleted/missing/invalid 404; clear recovery | [store.py](../backend/store.py), [main.py](../backend/main.py) | Recovery and expiration warning | Prior export repair regressions | Every authorized endpoint, exact boundary, cleanup isolation; reset does not extend TTL |
| Jobs and restart | Failed/timed-out work cannot publish; recover retained completed state | [jobs.py](../backend/jobs.py), [store.py](../backend/store.py) | Polling and reload | Store/API job tests | Real deadline, submission failure, pending-preview/store recreation and true process restart |
| CSV/XLSX export | Authorize, use active snapshot, neutralize formula-like text, retain original | [exports.py](../backend/exports.py), [main.py](../backend/main.py) | Download controls | Byte/cell-level engine/API and browser downloads | Every cell/type, variants/version switches, authoritative concurrent filename |
| JSON/HTML reports | Match active profile/findings/history; escape HTML | [exports.py](../backend/exports.py), [main.py](../backend/main.py) | Reports | Parsed report and XSS tests | Active cleaned/undo/redo content, response metadata and all-session errors |
| PDF printing | Authorized HTML in script-disabled sandbox, usable actual PDF output | [exports.py](../backend/exports.py) | Print action in [app.js](../frontend/app.js) | Existing print frame/PDF test | Chromium PDF and extracted text verified; native OS dialog remains unautomated |
| Python/PostgreSQL references | Active branch only; Python replay, PostgreSQL labels/unsupported comments/rollback | [exports.py](../backend/exports.py) | Reference downloads | Engine/API and browser tests | Executed Python replay and all SQL variants; SQL is not run against a database |
| Optional AI | Aggregate-only allowlist; deterministic fallback; no transformation authority | [ai.py](../backend/ai.py) | Status/explanation panel | Mock transport tests | Missing config/network/invalid/success/cache/quota/privacy cases and visible disabled fallback; live provider BLOCKED |
| UI shell and diagnostics | Existing navigation/themes/charts/errors/loading remain usable | [main.py](../backend/main.py) static assets | [app.js](../frontend/app.js), [ui.js](../frontend/ui.js), [charts.js](../frontend/charts.js) | Real section/theme/chart/mobile-size workflows | Shared console/network/page-error capture; not full visual/accessibility certification |
| Local API docs/deployment configuration | Bundled read-only schema viewer; public docs restriction; safe local build | [main.py](../backend/main.py), [Dockerfile](../Dockerfile), [render.yaml](../render.yaml) | [api-docs.js](../frontend/api-docs.js) | API/docs browser tests | Schema operations inspected/tested; image and cloud execution not verified |

Not implemented obligations: accounts, distributed workers, durable cloud retention, arbitrary database ingestion, server PDF rendering, automatic cleaning, ML-target/leakage workflows, LOF/Z-score fan-out or additional AI providers. These were not rebuilt under the guise of verification. See [BLUEPRINT_COMPARISON.md](BLUEPRINT_COMPARISON.md) for historical scope decisions.

## 4. Known fixtures and exact expected results

All fixtures are synthetic and isolated. The existing five bundled sample files retain their pre-verification SHA-256 hashes.

| Fixture | Verified expectations |
|---|---|
| Clean reference | 20 rows × 7 columns; zero missing cells and duplicate rows |
| Quality Issues | 21 × 10; one missing cell; one duplicate row; stable duplicate ID 20 |
| Quality Issues targeted findings | Region whitespace IDs 3, 8, 13, 18; missing amount 1; negative amount 8; invalid numeric 2, 9; invalid date 3; email 6; phone 7 |
| Statistical Anomalies | 102 × 3; one missing cell; IQR height IDs 30/100 and weight 39/100; MAD height/weight 100; Isolation Forest includes 100 and excludes incomplete row 101 |
| Multi-sheet workbook | All bundled sheets inspected/loaded with known headers, dimensions and cell values |
| Malformed input | Rejected explicitly; no partial baseline or modified original |
| Four-row lifecycle fixture | Whitespace name, two duplicate Bob rows, missing amounts, leading-zero/nonnumeric codes, invalid dates and A/B categories; exact values below |
| Generated engine/API fixtures | Empty/null/whitespace-only, mixed dtypes, ordered/unordered categoricals, constant/negative/infinite/extreme numerics, date boundaries, selected outliers, formula-like headers/cells and explicit limits |

### Cleaning operations

Each operation has engine/API invalid-parameter and nonmutation coverage. The UI lifecycle verifies preview count, approval gating, expected active version/values/IDs, undo, redo, reset, retained history, unchanged expiration, reload and CSV export. Variant and failure cases are enumerated in the matrix.

| Kind | Representative verified result / variants |
|---|---|
| `trim` | `" Alice " → "Alice"`; one affected row in the four-row fixture; bundled region trim changes four rows |
| `normalize_missing` | Explicit `"NA" → null`; one affected row; legitimate unselected tokens preserved |
| `drop_duplicates` | Selected duplicate ID 2 removed; IDs 0, 1, 3 retained; no automatic blanket deletion |
| `to_numeric` | Coerced codes become `[1, null, null, 3]`; invalid strict conversion, overflow and precision-loss cases reject atomically |
| `to_date` | Explicit format produces Jan 1 / Jan 4 ISO dates and two nulls with coercion; invalid formats/strict values reject |
| `fill_missing` | Constant zero produces `[1, 0, 0, 100]`; mean/median/mode variants tested, including categorical first-observed ties and all-null rejection |
| `drop_column` | Only selected category column removed; row IDs unchanged |
| `case` | Lowercase categories become `[a, b, b, a]`; upper/title variants also covered |
| `map_categories` | Explicit A→Alpha produces `[Alpha, B, B, Alpha]`; unselected labels remain |
| `handle_infinity` | Typed positive/negative infinities become null in engine/API tests. Browser exercises valid finite numeric no-op `[1,2,3]`; CSV `inf` text is not silently reclassified to create this case |
| `outliers` | Selected row ID 3 clipped from 100 to 10; unselected/null values unchanged; explicit removal and bound variants tested |

A chained 11-operation engine pipeline verifies operation ordering, Parquet persistence, CSV/XLSX outputs, executed Python replay and source nonmutation. API lifecycle variants additionally verify parent pointers, rejected/unapproved requests, reset/restore and retained branches.

## 5. API, authorization and lifecycle

The implemented OpenAPI surface has **27 method/path operations across 25 paths**, all exercised by API tests. Query variants are separate test cases where relevant, not extra schema operations. All paths below have prefix `/api/v1`; the [matrix endpoint cross-reference](DATAlENS_TEST_MATRIX.md#api-endpoint-result-cross-reference) links them to exact executed case IDs. These rows are coverage cross-references, not additional test counts.

| Method | Path | Verified result | Status |
|---|---|---|---|
| GET | `/health` | Health response and public request-rate limit | PASS |
| GET | `/samples` | Synthetic sample catalogue | PASS |
| POST | `/datasets/upload` | Capability/inspection; invalid/oversized input rejection, safe basename and no partial session | PASS |
| POST | `/datasets/sample/{sample_id}` | Four valid samples, intentional malformed sample and unknown sample | PASS |
| GET | `/datasets/{dataset_id}` | Authoritative version/revision/expiry; invalid operations leave metadata unchanged | PASS |
| POST | `/datasets/{dataset_id}/ingest` | Tracked v0 creation; readiness/busy/schema limits; forced executor failure redacted with no snapshot | PASS |
| GET | `/datasets/{dataset_id}/jobs/{job_id}` | Success/failure/timeout states; missing and cross-session job rejection | PASS |
| GET | `/datasets/{dataset_id}/preview` | Active values/stable IDs; pagination boundaries and readiness validation | PASS |
| GET | `/datasets/{dataset_id}/profile` | Exact synthetic statistics; persistence across store restart | PASS |
| GET | `/datasets/{dataset_id}/columns/{column:path}` | Existing column detail; missing column/readiness rejection | PASS |
| GET | `/datasets/{dataset_id}/quality` | Detected issues agree with exported report | PASS |
| POST | `/datasets/{dataset_id}/quality` | Explicit finite domain rules; invalid-rule rejection and nonmutation | PASS |
| GET | `/datasets/{dataset_id}/recommendations` | Synthetic issue recommendations; unready rejection | PASS |
| POST | `/datasets/{dataset_id}/anomalies` | IQR/MAD/two-feature Isolation Forest; invalid inputs reject without mutation | PASS |
| POST | `/datasets/{dataset_id}/cleaning/preview` | All 11 operation kinds; no publication; replacement invalidates old preview | PASS |
| POST | `/datasets/{dataset_id}/cleaning/apply` | Only JSON true plus matching preview/revision publishes; stale, unapproved and capacity rejection | PASS |
| POST | `/datasets/{dataset_id}/undo` | Parent snapshot restoration; v0 boundary rejection | PASS |
| POST | `/datasets/{dataset_id}/redo` | Undone snapshot restoration including restart; unavailable/cleared redo rejection | PASS |
| POST | `/datasets/{dataset_id}/reset` | Original v0, preserved history/expiry/capability, cleared redo/previews | PASS |
| POST | `/datasets/{dataset_id}/restore` | Existing version selection and new branch; unknown version rejection | PASS |
| GET | `/datasets/{dataset_id}/history` | Version/parent/operation history and active revision across navigation/restart | PASS |
| GET | `/datasets/{dataset_id}/export` | Actual CSV/XLSX snapshot bytes, MIME and source-vN filename; format/readiness/busy rejection | PASS |
| GET | `/datasets/{dataset_id}/report` | Actual JSON/HTML profile/issues/history, MIME and source-vN filename; invalid cases | PASS |
| GET | `/datasets/{dataset_id}/code` | Python/SQL active ancestor operations, text/plain and source-vN filename; invalid cases | PASS |
| GET | `/ai/status` | Local disabled/configuration/quota eligibility, not live-provider reachability | PASS |
| POST | `/datasets/{dataset_id}/ai/explain` | Deterministic fallback and mocked provider/cache paths; privacy and nonmutation | PASS |
| DELETE | `/datasets/{dataset_id}` | Authorized deletion; repeated-delete/busy rejection; synthetic cleanup cascading | PASS |

Every dataset-scoped operation is checked with valid ownership and missing, wrong or another dataset's token. Invalid/nonexistent IDs are rejected; an existing expired row with the valid capability returns 410, while invalid capabilities and already-cleaned rows return 404. Tokens are headers, not query parameters. Unsupported formats/options, validation errors, busy/capacity conditions and un-ingested readiness are covered without claiming success from an HTTP status alone.

**Reset is not session renewal.** It selects original v0, advances revision, clears stale review state/redo as defined and keeps retained history. It neither changes the capability nor extends the fixed expiration deadline. An expiration seen after reset can therefore be genuine expiration, not reset deleting the dataset. Controlled-clock tests cover exact boundaries; cleanup deletes only expired/deleted synthetic sessions and preserves a separate live session.

**Restart evidence:** actual Uvicorn stop/start against the same isolated store after upload→trim→undo; browser reload retains dataset/capability/expiry, redo restores v1, reset returns v0, another reload and CSV confirm the original value. Store recreation tests additionally retain profiles/history/pending previews and reject interrupted jobs. This verifies local persistent storage, not ephemeral cloud filesystem durability.

## 6. Export evidence

All six HTTP formats check correct endpoint/query, capability, response type, nonempty content, extension/source/version filename, active-version content and original/v0 preservation. The real Quality Issues lifecycle checks v0→trim v1→undo v0→redo v1. A separate concurrent-client regression proves filename/content agreement when the UI still caches v0 but another authorized client has published v1.

| Format | Endpoint / content type | Actual content verified | Scope/status |
|---|---|---|---|
| CSV | `GET /datasets/{id}/export?format=csv`; `text/csv` | Decoded full table vs active snapshot; 21 × 10; trimmed regions; leading-zero IDs; raw null-versus-empty quoting; protected formula-like strings/headers | Automated engine, API and browser |
| Excel XLSX | Same `/export?format=xlsx`; OOXML spreadsheet MIME | Opened workbook, sheet dimensions, every cell/header and data type; null/text/number/identifier handling; no unintended formula cells | Automated openpyxl inspection and real browser download; desktop Excel not tested |
| JSON summary | `/report?format=json`; `application/json` | JSON parsed; profile, findings and version history equal active API data | Automated engine, API and browser |
| Standalone HTML | `/report?format=html`; `text/html` | Meaningful report sections, escaped untrusted text, active profile/findings/history | Automated engine, API and browser; standalone report content checked |
| Python reference | `/code?language=python`; `text/plain` | Syntax compiled and generated transformation replay executed in documented checkout; active branch includes/excludes trim after redo/undo | Automated engine/API/browser; not a self-contained portable package |
| PostgreSQL reference | `/code?language=sql`; `text/plain` | Dialect label, active transformations, quoting, rollback safeguard; 24 translation variants, six explicit unsupported-operation outcomes, NUL rejection | Automated content validation; never executed against a database |
| Browser PDF | Authorized HTML report, then browser printing; no PDF API | Print frame/authorization/sandbox plus actual Chromium-generated PDF and extracted report text | Automated renderer output; native OS Save as PDF dialog is a separate untested step |

The final [actual PDF](../test-results/artifacts/workbench-active-region-tr-9cfa3-apshot-and-printable-report-chromium/active-v1-report.pdf) is **78,561 bytes**, begins with `%PDF-`, and was parsed with `pdftotext -layout`. Its [extracted text](../test-results/full-verification/active-v1-report.txt) contains `DataLens quality report`, `"rows": 21`, `"columns": 10`, `"active_version": 1`, `"kind": "trim"` and `"column": "region"`. This verifies document output, not just a print button or HTTP response. Native OS dialog interaction remains EXT-04.

Spreadsheet protection intentionally changes formula-like exported textual representations, never the stored original. Export fidelity is against the **active typed snapshot**, not the exact lexical bytes of an uploaded numeric CSV. Leading-zero string IDs are verified; a leading plus sign lost during earlier numeric inference cannot be recreated by export. See the separate semantic observations below.

## 7. Reproduced defects and fixes

| Defect | Evidence before fix | Root cause | Narrow change and regression |
|---|---|---|---|
| Earlier stale-session export failure | Cached Quality Issues v1 but metadata/profile/history and exports all returned 404; server retained zero datasets; report routes existed | Missing server session still represented as a usable browser workspace. Fixed 60-minute retention/cleanup is consistent with elapsed time; no historical deletion audit proves the exact deletion event | Confirm metadata before clearing session, actionable re-upload recovery, no futile retry, visible expiration warning in [app.js](../frontend/app.js). Existing six browser/seven API export regressions preserved |
| Stale version in downloaded filename | Client A cached v0; client B created v1; CSV contained trimmed v1 values but was called `verification-v0.csv` | Browser invented the filename from cached metadata; backend formerly supplied generic names | [main.py](../backend/main.py) creates sanitized source/version Content-Disposition under the same lock as bytes; [api.js](../frontend/api.js)/[app.js](../frontend/app.js) consume it, including RFC 5987. 27 added backend naming/readiness cases plus real-browser concurrency regression |
| Truthy nonboolean approval | `approved:1` published a new version in the repro | Boolean coercion accepted a value other than explicit JSON approval | Strict boolean in [models.py](../backend/models.py); numbers/strings reject with 422, false remains unapproved, true applies reviewed operation |
| Preview accepted at expiration instant | Apply at exact preview expiry returned 200 | Boundary comparison excluded equality | [store.py](../backend/store.py) rejects at/after expiry with 409 `stale_preview`; boundary regression passes |
| Ghost queued job after submit failure | Forced executor submission failure left a queued job and unusable bookkeeping | Submission exception did not terminalize the created job | [jobs.py](../backend/jobs.py) records failed/finished state and releases the processing slot; sanitized API failure and recovery tested |
| Categorical counts/mode used dictionary labels | Four focused cases failed: ordered/unordered mode chose `a` instead of first-observed `z`; frequencies included unused labels/reordered ties; all-null categorical invented an unobserved fill | Categorical `value_counts` dictionary semantics leaked into observed-value logic | [analysis.py](../backend/analysis.py)/[cleaning.py](../backend/cleaning.py) count an object view only, preserving stored dtype. Same four focused cases pass; full 371 engine tests pass |

### Failed attempts and test corrections — not hidden

- One early expanded API run reported a generic ingestion failure. Its cause was **not established**. Targeted cases and three subsequent complete owned API suites passed, followed by the final full 619-case run. No evidence justifies inventing a root cause or claiming the earlier failure never happened.
- Initial browser assertions incorrectly assumed filename separators/CSV quoting, selected the wrong quality category, or tried text `inf` as numeric input. Tests were corrected to the documented inputs/actual format while retaining value and integrity assertions; production ingestion was not relaxed.
- The first expanded browser run had 21/22 passing: Isolation Forest was given one feature despite its 2–20 feature contract. Selecting the second feature fixed test setup, not production behavior.
- The first complete 34-case browser run had **32 passed / 2 failed**. Both new lifecycle failures were synchronization defects in the test: the native dialog's asynchronous close handler had not yet started reset when an already-idle flag was read; one test observed v1 too early, another reloaded during the in-flight profile request (`ERR_ABORTED`). Tests now await the actual successful mutation response, then UI idle, and wait for initialization after reload. No failed-request/console assertion was removed. Trim, case and real restart subsequently passed **9/9 executions** (three repeats each), before the complete final rerun.

## 8. Logs, build and supporting gates

- Full Python [JUnit](../test-results/full-verification/python.xml) / [log](../test-results/full-verification/python.log): 619 passed, one warning, 61.95 seconds.
- Final Playwright [JSON](../test-results/full-verification/browser.json) / [log](../test-results/full-verification/browser.log); [HTML report](../playwright-report/index.html): 34 passed, zero unexpected/skipped/flaky, 173.349 seconds.
- Each browser case attaches `browser-evidence`: console errors, uncaught page errors, failed requests and HTTP errors. Uncaught page errors and unexpected 5xx fail the fixture. Intentional negative responses remain visible, not mislabeled as backend outages.
- Final [diagnostic totals](../test-results/full-verification/browser-diagnostics.json): **0 uncaught page errors, 0 failed requests, 16 console messages**. Six are expected blocked-script notices from the intentionally script-disabled report iframe (one in the integrated print workflow, five in the active-region print test). The other ten correspond exactly to negative HTTP cases: seven 404, one 410, one malformed-upload 422 and one injected transient-busy 429. All 22 added browser workflows have zero console errors, failed requests or HTTP errors. No unexpected 5xx, traceback or server ERROR was found in the final managed server log. The sandbox was not weakened to suppress its notices.
- Managed server log: `test-results/full-verification-server.log`. The restart case attaches its own server log. Test URLs contain synthetic IDs, not access-token query parameters; captured request diagnostics omit headers.
- Initial browser failure JSON/server log and targeted-repeat JSON remain in the ignored verification results directory. Final unique-case totals exclude those earlier attempts.
- `npm run check`, `npm run build`, Ruff, `pip check`, whitespace checks, five sample-hash comparisons and editor diagnostics are separate gates. No changed-file editor errors were reported.
- Warnings: Starlette TestClient/HTTPX deprecation; outdated Browserslist `caniuse-lite` data. Neither failed a gate. Dependencies were not upgraded just to suppress unrelated warnings.

The existing benchmark ran once on a seeded synthetic **2,000 × 5** CSV (93,641 bytes), with isolated storage and AI disabled. Upload 0.066029 s; parse 0.071274 s; profile 0.185282 s; quality 0.118244 s; anomalies 0.003576 s; cleaning 0.002383 s; export 0.030212 s; snapshot 25,282 bytes. Peak process RSS **207,844 KiB**, including imports. All 20 planted missing cells were detected; tiny IQR/MAD planted-outlier fixtures returned the expected ID. This is not a load test, scaling guarantee or general detection-accuracy estimate. Raw output: `test-results/full-verification/benchmark.json`.

## 9. Files changed

Production repairs: [backend/analysis.py](../backend/analysis.py), [backend/cleaning.py](../backend/cleaning.py), [backend/jobs.py](../backend/jobs.py), [backend/main.py](../backend/main.py), [backend/models.py](../backend/models.py), [backend/store.py](../backend/store.py), [frontend/api.js](../frontend/api.js), [frontend/app.js](../frontend/app.js). The last file includes the preceding export-session repair.

Regression tests/harness: [tests/test_api.py](../tests/test_api.py), [tests/test_store.py](../tests/test_store.py), new [tests/test_engines_full_verification.py](../tests/test_engines_full_verification.py), new [tests/test_system_verification.py](../tests/test_system_verification.py), [tests/browser/workbench.spec.js](../tests/browser/workbench.spec.js), new [tests/browser/full-verification.spec.js](../tests/browser/full-verification.spec.js), new [tests/browser/restart.spec.js](../tests/browser/restart.spec.js), new [tests/browser/fixtures.js](../tests/browser/fixtures.js), [tests/browser/server.mjs](../tests/browser/server.mjs), [package.json](../package.json).

Documentation: this report, [test matrix](DATAlENS_TEST_MATRIX.md), [current limitations](DATAlENS_KNOWN_LIMITATIONS.md), [VALIDATION.md](VALIDATION.md), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md), [ENGINEERING_OBSERVATIONS.md](ENGINEERING_OBSERVATIONS.md), [API_REFERENCE.md](../API_REFERENCE.md), [API_CONTRACT.md](API_CONTRACT.md), [ALGORITHMS.md](../ALGORITHMS.md), [DEVELOPMENT.md](../DEVELOPMENT.md).

## 10. Remaining limitations and manual actions

The local deterministic workflows and previously verified CSV ingestion, profiling, missing/duplicate findings, affected-row exploration, explicit approval, immutable version creation, undo and redo are covered by executed regression tests. No test evidence shows a regression in those workflows. This is not a guarantee for every possible input.

Phone-number measurement inference, identifier conversion recommendations, date-specific versus spelling checks and floating-point display policy remain **separate deferred engineering observations**, not silently fixed or claimed solved. See [ENGINEERING_OBSERVATIONS.md](ENGINEERING_OBSERVATIONS.md) and [current limitations](DATAlENS_KNOWN_LIMITATIONS.md).

No repetitive manual testing is required to establish the recorded local results. Optional remaining actions are external: select Save as PDF in the OS dialog when desired; review Python/SQL before using them elsewhere; arrange a separately authorized live provider/container/browser/desktop application check if needed. Already expired and deleted datasets must be re-uploaded and their reviewed transformations reapplied before the displayed retention deadline. Never expect reset or a frontend repair to recover deleted server files.

## 11. Reproduce the complete local regression

Use the existing configured environment and installed browser; no installation is necessary for this verified checkout. Run from the repository root, with port 8765 free. Do not point destructive integration tests at a real-user server/store.

```bash
mkdir -p test-results/full-verification
.venv/bin/python -m pytest -q --junitxml=test-results/full-verification/python.xml
.venv/bin/python -m ruff check backend tests scripts
.venv/bin/python -m pip check
npm run check
npm run build
PLAYWRIGHT_JSON_OUTPUT_NAME=test-results/full-verification/browser.json npm run test:browser -- --reporter=list,html,json
git diff --check
```

For the specifically corrected dialog/restart synchronization:

```bash
npm run test:browser -- --grep 'UI-trim:|UI-case:|restart' --repeat-each=3
```

The matrix links every executable test to its implementation and recorded result. Machine-generated logs/reports are ignored local artifacts; the three requested Markdown documents persist the verified outcomes in the repository without committing them.
