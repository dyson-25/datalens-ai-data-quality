# Validation evidence

Results describe local checkouts and synthetic fixtures, not production guarantees. Earlier dated sections below remain historical evidence.

## Final engineering pass

**642 Python tests and 42 real-backend Chromium workflows passed; no final failures or skips.** The pre-change Python baseline was 619 passing tests. Final Python runtime was 39.66 seconds; Chromium completed in 3.0 minutes. These are local measurements, not performance guarantees.

All required gates passed:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check backend tests scripts
npm run check
npm run build
npm run test:browser
.venv/bin/python -m pip check
git diff --check
```

Editor diagnostics found no errors in the changed source and test files. Non-blocking existing warnings remain: Starlette TestClient/HTTPX deprecation and outdated Browserslist data. No dependency upgrades were made.

### Root causes and repairs

- Fuzzy matching previously compared structured identifiers and similar labels without semantic/cardinality safeguards or frequency evidence. Conservative exclusions and review-only explicit mappings now prevent the covered false positives; uncertain suggestions are deliberately suppressed.
- Date profiling mixed ambiguous/invalid rows with valid format variation. Valid, ambiguous, invalid and missing counts are now distinct. Supported-format conversion validates calendars, blocks unresolved ambiguity even with coercion, and requires reviewed order selection.
- The numeric engine was already conservative, but the UI did not explain partially numeric columns. Readiness counts, invalid examples, selected-token null handling and explicit correction mappings now expose the existing approval workflow without weakening ingestion.
- Explicit business rules were limited to inclusive bounds. Optional whole-number and exclusive-minimum constraints now express positive prices and integer quantities/delivery days separately from statistical anomalies.
- The UI's high/critical count did not match backend severity values, overlapping findings could be confused with unique rows, and whitespace previews hid changes. Findings/row-occurrence/unique-row totals, classification labels and visible surrounding whitespace now clarify results.
- Unchanged operations previously published empty versions. No-op previews disable approval; the server rejects no-op publication while allowing dtype-only changes. Legacy analysis caches refresh lazily so existing sessions receive the corrected algorithms.

### Preserved behavior and browser evidence

The full suites retain immutable original/v0, stable row IDs, capability isolation, expiry/cleanup, stale/expired preview rejection, explicit approval, Undo/Redo/reset/restore, process restart, public limits, and CSV/XLSX/JSON/HTML/Python/SQL export coverage. The AI payload test includes the new invalid-example field and confirms it never leaves the aggregate-only privacy boundary. No live AI provider request was made.

New retail browser coverage exercises strict conversion failure, selected invalid tokens, cancellation, explicit mapping, numeric/date conversion, history, unresolved date ambiguity, no-op blocking, whitespace and explicit discount bounds. A theme test visits all five sections at 1440px and 390px in light and dark modes, checks page overflow, toggles the theme by keyboard and saves 20 screenshots in the ignored Playwright artifacts directory. Representative desktop/mobile screenshots were visually inspected. Existing reduced-motion, loading, failure/retry, hostile-content and authorized-download tests also passed. The existing light theme was retained; no theme rewrite was necessary.

Earlier full-run failures were obsolete expectations for mixed-date row IDs, weak fuzzy evidence, and approval of a no-op infinity fixture. They were updated to assert the refined contracts. A new browser assertion initially assumed integer formatting for API float bounds; the assertion now accepts both numeric representations. All were rerun successfully.

### Remaining limits

Spelling detection is a conservative heuristic, not proof of a typo or perfect personal-name recognition. Diagnostic examples/row IDs remain capped at 200, with exact totals and lower-bound labeling where needed. Domain rules are explicit, read-only and numeric-column-only; mixed columns require approved conversion first. Supported dates normalize to UTC and offset values may change calendar date. SQL date/numeric conversion remains deliberately untranslated reference output. This pass verifies Chromium, not every browser or a live deployment; native print dialogs and live AI availability are not certified.

No authentication, secret, Docker/Render, dependency, sample-data or infrastructure changes were made. No commit, push or deployment was performed.

## Complete verification — 2026-11-14

**619 Python tests and 34 real-backend Chromium workflows passed** (653 automated cases; zero final failures/skips/flaky results). The complete ledger defines 664 cases including four blocked and seven untested external/instrumentation scenarios. JavaScript syntax, production build, Ruff, dependency consistency, diff checks, editor diagnostics and all five original sample hashes passed. Actual six-format downloads and Chromium-rendered PDF contents were inspected.

See the [full report](DATAlENS_FULL_VERIFICATION_REPORT.md), [every-case matrix](DATAlENS_TEST_MATRIX.md) and [current limitations](DATAlENS_KNOWN_LIMITATIONS.md) for reproduced defects, changed files, earlier failed attempts, endpoint coverage and exact rerun commands. This audit made no live AI-provider requests, commits, pushes or deployments. Provider evidence in older sections is historical, not a current availability claim.

## Export/session repair — 2026-11-13 follow-up

### Root cause established before changes

The live browser retained `quality_issues.csv · v1` (21 rows × 10 columns), but the server no longer retained the dataset. Fresh requests using that browser session returned `404/not_found` for metadata/profile/history, CSV and Python exports, and JSON/HTML reports. The live OpenAPI schema contained the report route; frontend requests used the correct paths and `X-Session-Token`, including blob downloads and printing. A read-only check found **zero retained datasets** and the configured **60-minute TTL**.

The server had been running since approximately 12:01 UTC; failures appeared around 13:03 UTC. This is consistent with the fixed retention deadline and periodic cleanup. A retained expired row returns 410; after cleanup removes the row and files, authorization returns 404. There is no retained deletion audit proving which event removed this particular dataset. The confirmed fault was a **missing server session presented as a usable cached workspace**, not an absent report route or an export-specific authentication defect.

### Narrow repair and recovery

Only [frontend/app.js](../frontend/app.js) changed in production: confirmed unavailable sessions now clear stale browser state, display actionable recovery guidance and omit futile Retry controls. A report-only 404 rechecks dataset metadata and preserves a still-valid session. Reload uses the same recovery path. The existing lifecycle panel now displays the expiration deadline and deletion warning; layout/styles are unchanged. Suppressing Retry also avoids rendering a literal `null` placeholder.

The actual browser on port 8000 was refreshed and confirmed the missing-session recovery UI rather than the stale v1 workspace. No server restart, database migration, retention-policy change or backend export rewrite was needed. An already removed server original/snapshot cannot be recovered by repairing the frontend: **re-upload the original or reload the sample, repeat the reviewed trim/approval, and export before the displayed deadline**.

### Final regression evidence

```bash
npm run build && npm run check && npm run test:browser && \
  .venv/bin/python -m pytest -q && \
  .venv/bin/python -m ruff check backend tests scripts && git diff --check
```

**402 Python tests passed (12.11 s); 12 Chromium tests passed (44.3 s); production build, JavaScript syntax checks, Ruff and diff checks passed.** Existing tests were retained. The original release results below are historical, not the latest counts.

- **CSV and Excel XLSX:** actual downloaded bytes; every decoded cell/header compared against the active snapshot, including 21 × 10 dimensions, leading-zero IDs, trimmed regions, and CSV missing-versus-empty quoting. XLSX checked for unintended formula cells.
- **JSON quality summary and standalone HTML report:** parsed profile, findings and history match the active API results. HTML sections decode to the same report content.
- **Python transformation reference and PostgreSQL SQL reference:** downloaded files contain the active region trim, replay/reference scaffolding and SQL rollback safeguard; undo excludes the trim, redo restores it. These remain reference artifacts, not a new executable SQL integration.
- **Browser PDF printing:** the real print action creates the authorized report frame and requests printing. Chromium generated a real PDF from that printable document. `pdftotext` verified the title, 21-row profile, active version 1 and region-trim history. Native OS print-dialog interaction is not automated; the user still selects **Save as PDF**.
- **Authorization:** all six HTTP download routes reject missing, wrong and other-session tokens, invalid/nonexistent IDs, retained expired sessions (410), and cleaned-up sessions (404).
- **Lifecycle regression:** removed, expired and invalid-token sessions recover without stale state; startup/reload recovery works; an isolated missing-report route does not clear a valid session; reloading a sample after removal produces a valid JSON download.
- **Existing behavior:** the actual synthetic fixture exercises preview (four affected region rows), rejection without approval, approved v1 creation, undo to v0 and redo to v1. All six HTTP outputs are checked at each state. Original-upload and v0 snapshot bytes remain unchanged during retained-session exports. Existing ingestion, profiling, missing/duplicate findings, affected-row and cleaning/version tests also pass.

The pre-fix stale-session browser regression failed as expected. A new CSV test initially assumed Python 3.12's reader restored unquoted nulls; its expectation was corrected and raw quoting assertions retained. An ad-hoc PDF assertion initially used incorrect title capitalization; matching the actual title passed. **No test failures remain.** Non-blocking warnings remain for outdated Browserslist data and Starlette's TestClient/HTTPX deprecation.

The four unrelated semantic/presentation improvements are recorded separately in [engineering observations](ENGINEERING_OBSERVATIONS.md), not implemented. No secrets, working ingestion/cleaning behavior, backend architecture or database were changed. **No commit, push or deployment was performed for this repair.**

## Backend integration, storage and optional AI

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_store.py tests/test_ai.py -q
```

**142 passed in 10.10 seconds.** One dependency deprecation warning: Starlette's TestClient currently uses HTTPX; this is not a test failure. VS Code test discovery did not find the tests, so the repository pytest command was used.

Covered: CSV/XLSX ingestion, worksheet/header selection, profiling, quality/recommendations, explicit domain bounds, approval-required previews, immutable originals, snapshot publication/rollback, undo/redo/reset/restore and branching, stale approvals, ownership checks, expiration, reports matching live analysis/history, valid CSV/XLSX exports, reference code, malformed inputs, public limits, interrupted jobs, orphan recovery, per-session job cap, and zero-cost AI behavior.

AI tests use deterministic HTTP mocks. Separately, one actual OpenRouter connection with the existing private configuration returned `source=ai` and a validated explanation. Only synthetic aggregate counts were supplied; no raw rows, column names, key or private dataset was transmitted. This proves one request succeeded, not guaranteed future availability.

Focused Ruff checks passed. Editor diagnostics reported no errors for the primary API, models and integration tests.

## Full backend regression

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check backend tests scripts
```

**Final release regression: 395 passed in 12.05 seconds; Ruff passed.** This includes 252 deterministic-engine tests plus 143 integration/storage/AI tests (the earlier 142-test run above, plus an offline-docs regression). Engine editor checks are clean. CSV quoting, structural blanks, literal null tokens, leading-zero identifiers, reserved row-ID collisions, XLSX formula text, all 17 quality rules, anomaly edge cases, cleaning previews, exports and generated-reference safeguards are covered.

## Frontend and actual browser verification

```bash
npm run build
npm run check
npm run test:browser
```

Production build and JavaScript syntax checks passed. **All 6 Chromium tests passed in 25.4 seconds** against the real backend, covering:

- Sample ingestion, profiling, versioned approved cleaning, undo/redo/restore and authorized downloads/report printing.
- CSV upload/raw-value preservation, accurate trim preview and preview invalidation after editing.
- Empty, unsupported and malformed uploads.
- Untrusted headers/values staying text in tables/charts; responsive mobile layout and theme changes.
- Excel worksheet selection and workbook export.
- Locally bundled OpenAPI documentation and filtering.

Six actual synthetic-data screenshots are in [screenshots](screenshots/). These are real application captures, not UI mockups. Browser coverage is Chromium-only. Browserslist reported an outdated compatibility dataset; the build still passed.

Separately, the primary agent started the actual local server on loopback, verified healthy status and `/docs` HTTP 200, visually checked responsive charts, confirmed 27 documented endpoints and exercised an amount maximum-100 domain rule (10 affected records, no snapshot mutation). The synthetic verification session was deleted through the UI and the temporary server was stopped. No Docker-build success is claimed.

## Statistical and performance measurements

Reproducible command:

```bash
.venv/bin/python -m scripts.benchmark
```

The first run identified a CSV ingestion edge case: structural blanks prevented numeric inference. This was fixed and regression-tested: unquoted blanks become null, while quoted empty strings and literal null tokens are preserved. The benchmark then completed successfully.

Synthetic fixture: **2,000 rows × 5 columns**, seed 42, CSV 93,641 bytes. Single warm-process run:

| Stage | Seconds |
|---|---:|
| Upload/inspection/persistence | 0.046447 |
| Parsing | 0.066331 |
| Profiling | 0.141057 |
| Quality detection | 0.057853 |
| IQR anomaly detection | 0.001568 |
| Trim transformation | 0.000979 |
| CSV export | 0.021421 |

Snapshot: **25,282 bytes**. Process peak RSS: **393,544 KiB (~384 MiB)**, including imports and the test application. Detected **20/20 planted missing cells** and four quality issue groups.

On the deliberately small fixture `[1, 2, 3, 4, 100]`, IQR (1.5) and modified MAD (3.5) both identified exactly stable row ID 4: precision 1.0, recall 1.0. These are fixture checks, **not general anomaly-detection accuracy claims**, production capacity estimates, cold-start results or concurrency benchmarks.

## Security and privacy

Independent reviews of core API/storage/AI and completed engines/frontend/container configuration both reported no vulnerabilities. Capability isolation, spreadsheet formula neutralization, untrusted text handling, preview approval, bounded parsing and zero-cost AI controls also have automated regression coverage. This is a bounded code review, not a penetration-test certification or proof of absence of vulnerabilities.

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| — | — | Backend, frontend and container configuration | — | No vulnerabilities reported in either completed review | — |

Private environment, virtual environment, storage and original planning PDF remain ignored. The reference PDF SHA-256 matches its initial value: `4d50aacc7b88f73d76a26608fa35bcad06199b6328369c0cd977ac40275af3ce`. The environment file was not edited.

## External release gates

- Docker: actual build attempt exited 127 because the executable was unavailable; no daemon/socket or alternative engine available. Configuration prepared, **image build unverified**.
- GitHub: **published** to `dyson-25/datalens-ai-data-quality`, branch `main`. Initial HTTPS push failed with disabled username prompting; existing SSH authentication succeeded. `git ls-remote origin refs/heads/main` matched local `9c6387763d0e3d19351ec35c3b7009d78ed1952a` after the release push. Subsequent documentation status commits use the same verified publication path.
- Render: no authorized deployment access; **not deployed**.
