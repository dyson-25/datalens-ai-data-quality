# DataLens

A temporary, single-user-per-dataset workbench for inspecting, profiling, and reviewing changes to CSV/XLSX data. FastAPI serves the browser UI and API; SQLite metadata and immutable Parquet snapshots live on local, capped storage. No permanent accounts or hosted database are required.

## Status and scope

The parent verified the final release regression on **2026-11-13**: **395 pytest tests passed in 12.05 seconds**, Ruff was clean, `npm run build` and `npm run check` succeeded, and **6 real-backend Chromium tests passed in 25.4 seconds**. Six actual synthetic screenshots were generated. A synthetic benchmark also completed; see [measured results and limits](DEVELOPMENT.md#known-integration-observations).

Independent bounded reviews of the core and engines/frontend/container configuration reported **no vulnerabilities**. This is not a security certification or proof that vulnerabilities are absent. The parent visually checked responsive dashboard behavior, the local `/docs` viewer rendering 27 endpoints, and an `amount` maximum-100 quality check reporting 10 affected records without changing the version.

On the same date, a minimal synthetic aggregate-only OpenRouter check returned `source: ai`, no error reason and a nonempty explanation from `openrouter/free`. This is a point-in-time connection check, not an availability guarantee. No raw data or credentials were disclosed.

The Python 3.12 release lock has been generated. [docs/VALIDATION.md](docs/VALIDATION.md) is the consolidated evidence record, being updated by the parent. Docker build was explicitly attempted and exited **127 (`docker` not found)**; no image build, container execution or deployment success is claimed. Backend/browser evidence and bounded security reviews are complete. The initial HTTPS push failed with exit **128**, but the parent recovered using existing SSH authentication: the push succeeded, and an HTTPS remote-branch check matched the local HEAD at verification time. **Repository publication is verified**; the original HTTPS remote was preserved. Final follow-up documentation still requires its separate commit/push. See [future SSH push and verification](DEPLOYMENT.md#local-authentication-and-manual-push). Render authentication remains unavailable.

| Area | Intended behavior / qualification |
| --- | --- |
| Import | CSV/XLSX inspection, sheet/header/encoding/delimiter choices, bounded asynchronous ingestion |
| Analysis | Cached per-version profiles, quality issues, suggested operations, IQR/MAD/Isolation Forest findings; heuristics require review |
| Cleaning | Review server-held preview before explicit approval; original source retained unchanged |
| History | Parent-linked branches, undo/redo/reset and explicit restore; not a permanent audit archive |
| Downloads | CSV/XLSX data, JSON/HTML reports, Python reference code and **PostgreSQL reference dialect** SQL |
| PDF | Optional browser print-to-PDF of an HTML report; no native PDF endpoint or bundled report PDF |
| AI | Optional aggregate-only explanations, off by default; no raw rows, samples, or column names sent to the provider |
| Hosting | Optional Render free-plan blueprint; not deployed or production-certified |

## Quick start

Use Python 3.12, Node.js 22 and npm. Preserve any existing private `.env` and `.venv`; do not overwrite or publish them. From the repository root, after creating/activating a virtual environment if needed:

```bash
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
npm ci
npm run build
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

The release lock filename is `requirements.lock.txt`. If not yet generated, local development can use `requirements.txt` instead; the Docker build intentionally requires the lock. See [installation](INSTALLATION.md) for creating a new environment and safely using `.env.example`.

Open `http://127.0.0.1:8000`. Select a synthetic sample or upload a non-sensitive file, inspect import options, ingest and poll, then review the profile and cleaning preview before applying. For known business bounds, use the [read-only domain-rule API](API_REFERENCE.md#domain-rule-quality-checks) to check selected columns; it does not change versions or automatically clean data. Export useful work before the session expires. Each dataset has its own capability token; losing it means uploading again.

## Operational limits

Run **one Uvicorn worker and one service instance**. Heavy operations share one nonblocking slot and competing work receives HTTP 429. Ingestion timeout is cooperative: Python cannot forcibly kill its worker thread; the slot stays occupied until that thread exits. A timed-out snapshot is not published. This is not a hard CPU/memory isolation guarantee.

Public/cloud defaults cap uploads at 5 MiB, 10,000 rows, 50 columns, 10 datasets, and 256 MiB storage. Local defaults are larger. Sessions expire after 60 minutes; cleanup can wait for an occupied slot. Render restarts/redeploys/spin-down discard local data. There are no durable accounts, cross-device recovery, or multi-worker guarantees.

## Synthetic screenshots

Captured by the verified local Chromium workflow, not a hosted deployment:

[Dark dashboard](docs/screenshots/dashboard-dark.png) · [Light dashboard](docs/screenshots/dashboard-light.png) · [Column profiler](docs/screenshots/column-profiler.png) · [Mobile overview](docs/screenshots/mobile-overview.png) · [Quality lab](docs/screenshots/quality-lab.png) · [Cleaning studio](docs/screenshots/cleaning-studio.png)

## Documentation

- [Installation and settings](INSTALLATION.md)
- [Architecture](docs/ARCHITECTURE.md) and [API contract](docs/API_CONTRACT.md)
- [API reference](API_REFERENCE.md) and [algorithms](ALGORITHMS.md)
- [Security and privacy](SECURITY.md)
- [Development and test commands](DEVELOPMENT.md)
- [Deployment, cost caveats, and verification](DEPLOYMENT.md)
- [Roadmap and unsupported capabilities](ROADMAP.md)
- [Validation evidence — tests and bounded reviews complete; deployment blocked](docs/VALIDATION.md)
- [Final report — 15-category delivery summary](docs/FINAL_REPORT.md)
