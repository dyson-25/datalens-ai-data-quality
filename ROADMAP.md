# Roadmap and boundaries

This is a release roadmap, not a deployment guarantee. The parent verified **395 Python tests in 12.05 seconds**, clean Ruff checks, successful npm build/check commands, and **6 real-backend Chromium tests in 25.4 seconds**. The synthetic benchmark, dependency lock, `pip check` and six actual synthetic screenshots are recorded. Independent bounded core and engines/frontend/container-configuration reviews reported no vulnerabilities; this is not certification. Docker build exited 127 (`docker` not found); container execution and authenticated Render deployment remain blocked, and Git push is pending. See [docs/VALIDATION.md](docs/VALIDATION.md).

## Release acceptance work

1. Preserve the completed bounded security-review findings and final backend/browser regression evidence; extend coverage when behavior changes.
2. Preserve the verified full Python-suite, lint and benchmark results in the consolidated record, including environment constraints.
3. Verify ingestion limits and cooperative timeout semantics: the slot stays held until thread exit, and timed-out snapshots remain unpublished.
4. Verify dataset-separated capabilities, preview approval, stale revision conflicts, version branches/restoration and cached profiles.
5. Verify formula-safe exports, HTML escaping, PostgreSQL reference code caveats and aggregate-only AI payloads.
6. Preserve the verified synthetic browser evidence and six actual screenshots; extend coverage as needed without inferring exhaustive accessibility results.
7. Build/run the container using the generated `requirements.lock.txt` once Docker is available; the current build attempt was blocked by the missing executable.
8. Complete and verify Git push, then optionally deploy the free Render blueprint only after authentication, billing review and an explicit operator decision. Record the actual URL and smoke-test evidence only after deployment.

## Deliberate current boundaries

- Temporary, capped dataset sessions; no permanent accounts or durable recovery.
- One service instance and one Uvicorn worker; no distributed queue or multi-worker safety claim.
- Cooperative ingestion deadline, not hard thread cancellation or process isolation.
- CSV/XLSX ingestion; no PDF/OCR import, arbitrary database connectivity or macro execution.
- Optional HTML print-to-PDF rather than native server-side PDF generation.
- Python/SQL reference export rather than automatic code execution; SQL targets a PostgreSQL reference dialect, not every database.
- Optional aggregate-only AI explanation; no raw-data provider disclosure or autonomous cleaning.
- Synthetic single-run measurements only; no production throughput guarantee, SLA, compliance certification or zero-spend guarantee.

## Possible later work, not implemented commitments

- Isolated ingestion processes with enforceable CPU/memory/time limits.
- Distributed coordination before allowing multiple workers or replicas.
- Durable storage and identity only after a separate retention/privacy/access-control design.
- Broader reproducibility tests and dialect-specific executable export support.
- Independent accessibility and security assessments, and benchmarks with reproducible hardware/data descriptions.

Paid storage or infrastructure is not provisioned by the current blueprint. Any future resource change requires a fresh cost and privacy review.
