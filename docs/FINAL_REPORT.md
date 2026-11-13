# DataLens — final engineering report

Release verification date: **2026-11-13**. The local application is implemented and verified. **Container execution and public deployment remain incomplete external release gates.**

## 1. Product

A local-first CSV/XLSX quality workbench with deterministic profiling, seventeen quality rules, statistical anomaly review, explicitly approved reversible cleaning, charts, exports and optional zero-cost aggregate AI explanations. Five integrated workspaces connect upload, profiling, quality/anomalies, cleaning and reporting.

## 2. Architecture

Single-process FastAPI modular monolith; SQLite metadata and immutable Parquet snapshots; stable row IDs, parent-linked version branches, revision-based stale-approval protection, private originals and capability-authenticated dataset access. One processing gate and bounded ingestion jobs prevent unbounded task accumulation. Vanilla JavaScript uses locally bundled assets, with no CDN dependency.

See [architecture](ARCHITECTURE.md), [decisions](ARCHITECTURE_DECISIONS.md) and [API contract](API_CONTRACT.md).

## 3. Stack

Python 3.12.3, FastAPI, Pydantic, Pandas, NumPy, PyArrow, SciPy, scikit-learn, OpenPyXL, SQLite and HTTPX. Node 22.23.4, ECharts 5.6.0, Tailwind 3.4.19 and Playwright 1.65.0. Actual dependency versions are pinned in the Python and npm lockfiles. Uvicorn runs one worker.

## 4. Implemented features

- CSV validation, encoding/delimiter/header handling; XLSX worksheet selection; bounded preview; five reproducible synthetic samples.
- Conservative inference preserves identifiers, quoted empty strings and literal null tokens; structural CSV blanks are missing. XLSX formulas remain untrusted text, never evaluated.
- Dataset/column profiles, missingness, duplicates, numeric distributions, category frequencies, correlations, interactive charts and seventeen quality rules.
- Optional explicit numeric domain ranges; IQR, modified MAD and bounded opt-in IsolationForest. Findings are suggestions requiring human judgment.
- Cleaning operations with exact previews, explicit approval and stored operation payloads: trimming, missing-token normalization, duplicate removal, numeric/date conversion, imputation, column removal, case normalization, category mapping, infinity handling and explicit outlier handling.
- Immutable originals/snapshots; undo, redo, reset, historical restore, preserved branches, restart recovery and TTL cleanup.
- Formula-safe CSV/XLSX, matching JSON/HTML reports, local browser print/save-as-PDF and downloadable Python/PostgreSQL reference code.
- Responsive dark/light UI, error/empty/loading states, affected-row inspection and authorized Blob downloads.
- Locally bundled read-only OpenAPI viewer with 27 endpoints; normal operation works without AI.

## 5. Deferred and bounded features

No multiworker/distributed processing, hard parser-process cancellation, durable cloud dataset storage, user accounts, cross-device capability recovery, at-rest encryption, huge-file streaming, server-side PDF renderer or execution of generated code. Browser automation covers Chromium only. Dates require explicit conversion; PostgreSQL references identify unsupported exact translations. Domain checks are ad hoc and are not added to standard exported reports. See [known limitations](KNOWN_LIMITATIONS.md).

## 6. Tests

**395 Python tests passed in 12.05 seconds** and **6 real-backend Chromium browser tests passed in 25.4 seconds**. Production asset build, JavaScript syntax checks and Ruff all passed. Relevant editor diagnostics were clean. One dependency deprecation warning and one outdated Browserslist-data warning are documented, not concealed.

Tests exercise ingestion, all rule/operation families, numeric edge cases, source preservation, preview approval, branching/history, stale requests, ownership, export/report integrity, unsafe text, formula neutralization, resource limits, AI pricing/quota/fallback controls and the connected browser workflows. [Complete evidence and commands](VALIDATION.md).

## 7. Statistical benchmark

All **20/20 planted missing cells** were detected. For `[1,2,3,4,100]`, IQR at 1.5 and modified MAD at 3.5 each flagged exactly row ID 4, giving precision and recall 1.0 **on this tiny fixture only**. No population-level accuracy claim is made.

## 8. Performance and memory

One synthetic 2,000 × 5 run, seed 42: upload 0.046447s; parse 0.066331s; profile 0.141057s; quality 0.057853s; IQR 0.001568s; trim 0.000979s; CSV export 0.021421s. CSV size 93,641 bytes; Parquet snapshot 25,282 bytes. Import-inclusive process peak RSS **393,544 KiB (~384 MiB)**. These are warm-process observations, not concurrency, cold-start or hosting-capacity guarantees.

## 9. Security and privacy

Two independent bounded code reviews covered the core and the completed engines/frontend/container configuration. No vulnerabilities were reported; this does not prove absence of vulnerabilities.

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| — | — | Backend, frontend and container configuration | — | No vulnerabilities reported | — |

Dataset IDs alone grant no access. Capabilities are supplied in headers, never URLs. CSP, escaped text, formula-safe exports, strict approval bodies and bounded parsing are implemented. Private environment, virtual environment, runtime datasets/databases and the original planning PDF are excluded from Git and container context. The PDF's original SHA-256 is unchanged; the private environment was not edited. See [security guidance](../SECURITY.md).

## 10. AI status

Optional HTTPX gateway permits only `openrouter/free`, verifies zero pricing, constrains providers, persists quotas/cache and falls back deterministically. A real minimal connection succeeded with synthetic aggregate counts and returned an AI explanation. No raw rows, column names or secrets were transmitted. Availability is not guaranteed; public configuration defaults AI off. No paid fallback is permitted.

## 11. Git milestones

- `6c9a3da` — validated storage/API foundation.
- `36a1542` — zero-cost optional AI gateway.
- `09a7f0a` — deterministic engines and synthetic fixtures.
- `7e3857c` — integrated workbench, browser workflows, screenshots and benchmarks.
- `9c63877` — release documentation, measured evidence and deployment configuration.

Publication-status documentation follows in the repository history. Every milestone was staged explicitly and checked for private paths/secrets before commit.

## 12. GitHub

**Published successfully** to [dyson-25/datalens-ai-data-quality](https://github.com/dyson-25/datalens-ai-data-quality), branch `main`. Initial HTTPS push failed because interactive username prompting was disabled. Existing SSH authentication succeeded without changing stored remote settings. The remote branch was verified against local commit `9c63877` after publication; the final documentation update is published through the same path. This publishes source and evidence, not a running web deployment.

## 13. Docker

Multi-stage Node/Python image, nonroot runtime, explicit runtime asset copies, private-context exclusions, bounded native thread pools, dynamic `PORT` and one Uvicorn worker are configured. **Actual `docker build -t datalens:local .` failed with exit 127 because Docker is not installed.** No available daemon/socket or alternate engine was found. Static review and native application tests do not substitute for an image build.

## 14. Render

Free-plan blueprint and deployment instructions are prepared with conservative public limits and AI disabled. **No public service was deployed or verified:** authorized account/deployment access is unavailable. Free hosting has sleep, ephemeral-filesystem and quota/billing caveats; permanent zero hosting cost cannot be guaranteed.

## 15. Remaining manual actions

1. Use a machine with Docker to build and run the image, then verify `/api/v1/health`, upload/clean/export and memory behavior.
2. Authorize Render deployment from the repository, select the free plan, inspect billing/spending settings and verify the actual public URL before sharing it. Never upload private data to a public demonstration.
3. Future pushes can reuse the verified SSH path without changing the HTTPS fetch URL:

```bash
git -c remote.origin.pushurl=git@github.com:dyson-25/datalens-ai-data-quality.git push origin main
```

4. To run locally:

```bash
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Open `http://127.0.0.1:8000`. The temporary verification server was stopped after use. See [installation](../INSTALLATION.md) and [deployment](../DEPLOYMENT.md) for complete instructions.

[Six genuine application screenshots](screenshots/) were captured from bundled synthetic data, including desktop, mobile, light/dark, profiler, quality and cleaning views.
