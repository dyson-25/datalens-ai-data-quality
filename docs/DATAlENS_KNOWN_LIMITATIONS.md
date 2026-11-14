# DataLens — current verification limitations

Verified scope: **2026-11-14 UTC**, local uncommitted checkout described in the [full report](DATAlENS_FULL_VERIFICATION_REPORT.md). The [complete matrix](DATAlENS_TEST_MATRIX.md) defines **664 cases: 653 executed and passed, 0 final failures, 4 blocked, 7 not tested**. The passing cases comprise 619 Python tests and 34 real-backend Chromium workflows. These results are not universal correctness, production-readiness or security certification.

## Explicit gaps and external prerequisites

These are the same eleven external cases as the matrix, not additional failures or tests. They must not be counted as passing.

| ID | Scenario | Status | What is established / what remains |
|---|---|---|---|
| EXT-01 | Live AI provider | BLOCKED | No live provider request was made or private credentials inspected in this audit. Mocked provider success, malformed response, network failure, quotas, aggregate privacy and deterministic fallback passed. Live testing needs separate authorization for external processing and any account requirements; historical provider success is not current availability evidence. |
| EXT-02 | Docker image runtime | BLOCKED | Docker is unavailable. Container configuration was inspected, but the image was not built or run. A Docker-enabled environment is needed for this gate. |
| EXT-03 | Public deployment | BLOCKED | The user explicitly prohibited automatic deployment. No push or public deployment was attempted; deployment must remain separately authorized. |
| EXT-04 | Native OS Save as PDF dialog | NOT TESTED | The authorized script-disabled report frame and actual Chromium PDF rendering passed. The resulting 78,561-byte PDF contains the report title, 21 rows, 10 columns, active v1 and region trim. Native dialog selection and OS-specific output destinations were not automated. |
| EXT-05 | Desktop Excel / LibreOffice display | NOT TESTED | Actual downloaded XLSX bytes and workbook cell values/types were inspected with openpyxl. Desktop formatting, locale rendering and application-specific behavior were not tested. |
| EXT-06 | PostgreSQL execution | NOT TESTED | PostgreSQL reference content, quoting, supported/unsupported translations and rollback safeguard passed. No generated SQL was executed against a database. It is a review reference, not a migration or an exact SQL implementation of every pandas operation. |
| EXT-07 | Firefox | NOT TESTED | Only the configured Chromium project ran. |
| EXT-08 | WebKit | NOT TESTED | Only the configured Chromium project ran. |
| EXT-09 | Instrumented statement/branch coverage | BLOCKED | The selected environment lacks coverage/pytest-cov. No new instrumentation dependency was installed and no coverage percentage is claimed. The complete collected-case ledger is not line/branch coverage. |
| EXT-10 | Sustained production capacity / soak | NOT TESTED | Bounded concurrency/limits and a seeded 2,000-row benchmark passed. This does not establish production throughput, large-scale memory safety or prolonged multiuser behavior. Multiple backend workers are unsupported. |
| EXT-11 | Full accessibility / visual certification | NOT TESTED | Browser controls, themes, charts and mobile-sized layouts were exercised. No screen-reader audit, complete keyboard-only certification or cross-platform pixel comparison was performed. |

## Session and storage boundaries

- **Fixed retention, not sliding inactivity:** the default deadline is 60 minutes from session creation. Cleaning, export, undo/redo and reset do not renew it. Reset selects immutable v0; it does not create a new session or delete an otherwise live session.
- **Deletion is irreversible within the app:** cleanup removes original uploads, snapshots and metadata. Valid authorization against a retained expired row returns 410; missing/deleted sessions and invalid capabilities return 404. A browser label is not proof the server still retains that dataset. The recovery UI now clears confirmed unavailable state and requests re-upload/reloading the source. There is no retained deletion audit proving the exact event that removed the previously reported dataset.
- **Capabilities and tabs:** possession of a dataset capability grants access. Browser selection is tab-local. There are no user accounts, roles, cross-device recovery or encrypted-at-rest storage. A separately opened tab does not automatically inherit the original tab's selection.
- **Local persistence:** the actual process restart test preserved the isolated local SQLite/Parquet store. It does not prove durability on an ephemeral cloud filesystem or across redeployment. Interrupted jobs are not resumed.
- **Single process:** one global gate serializes expensive work. Ingestion timeouts are cooperative; they prevent late publication but cannot forcibly terminate an unresponsive native parser. Its slot remains held until the worker exits.
- **Cross-client freshness:** another authorized client can change the active version while a UI retains older displayed metadata. Download names and bytes are now derived from the same authoritative active snapshot. Automatic cross-tab synchronization or a live-updating history view is not implemented.

## Data and export boundaries

- Export correctness is relative to the **active typed snapshot**, not byte-identical reproduction of the input CSV. Original bytes and immutable baseline snapshots remain preserved until session deletion/expiry. Numeric/date parsing can change lexical representation; lost lexical formatting cannot be reconstructed by export.
- CSV distinguishes an unquoted null from a quoted empty string. Leading-zero textual identifiers are covered. Excel formulas are treated as untrusted text, never evaluated by the application. Spreadsheet formula neutralization intentionally changes exported text representations without changing the stored dataset. Mixed workbook scalar types may require string storage.
- CSV `inf` / `-inf` text is not automatically interpreted as numeric infinity. The browser infinity-operation test exercises a valid finite no-op; actual positive/negative infinity replacement is established by typed engine/API fixtures, not claimed for this CSV UI path.
- Reference Python replay was actually executed in the documented checkout. It relies on that project environment; it is not a self-contained portable package. PostgreSQL remains reference-only, and browser PDF has no server PDF endpoint.
- Statistical/semantic findings and anomaly scores are review suggestions, not proof that records are wrong. Seeded examples verify deterministic arithmetic and planted IDs, not real-world precision/recall. Isolation Forest requires its documented multivariate inputs.

## Deferred semantic improvements — intentionally not mixed into repairs

The separate [engineering observations](ENGINEERING_OBSERVATIONS.md) remain open:

1. Phone numbers should not automatically be treated as numeric measurements; early numeric inference may lose a leading plus sign.
2. Identifier-like columns should avoid inappropriate numeric-conversion recommendations.
3. Date columns should receive suitable date checks rather than irrelevant spelling suggestions.
4. Numeric display should avoid floating-point presentation artifacts without silently changing stored values.

These were not silently implemented, relaxed in tests, or declared solved by the export repair. The observed categorical frequency/mode defects were separate reproduced defects fixed during the broader verification.

## Evidence caveats

The final automated suite has zero failures, skips or flaky results. Earlier failed attempts are retained and explained in the [full report](DATAlENS_FULL_VERIFICATION_REPORT.md), including one early generic API ingestion failure whose cause was not established and later successful reruns. This is not evidence that an intermittent failure can never recur.

Final browser evidence contains zero uncaught page errors, zero failed requests and no unexpected 5xx. Six blocked-script console messages are the intentional report iframe sandbox; ten other console messages correspond to deliberate negative HTTP cases. The sandbox was not weakened to suppress them. Some transient/missing-route cases are injected faults; core ingestion/cleaning/export workflows use the real backend.

Dependency deprecation and stale Browserslist-data warnings remain nonblocking. No unrelated dependency upgrade was made. The small benchmark is a supporting check, not a capacity guarantee.

## Remaining actions

No repetitive manual retesting or screenshots are needed to establish the recorded local results. To recover an already removed dataset, re-upload the original or reload the sample, reapply the reviewed transformations, and export before its displayed deadline. Select **Save as PDF** in the native dialog when using that feature. Review reference scripts before use elsewhere. Additional live-provider, container, browser-engine, desktop-application or deployment checks are optional separate work subject to the explicit prerequisites above. All changes remain local and uncommitted; no push or deployment was performed.
