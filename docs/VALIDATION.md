# Validation evidence

Verified locally on 2026-11-13. Results describe this checkout and synthetic fixtures, not production guarantees.

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
