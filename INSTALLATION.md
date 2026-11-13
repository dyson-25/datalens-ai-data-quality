# Installation

## Prerequisites

- Python 3.12 and its virtual-environment support; Node.js 22 and npm.
- A writable local storage directory and enough space for original uploads, snapshots, dependencies, and builds.
- Docker is optional. PostgreSQL, Redis, permanent accounts, and an AI API key are not required.

Commands below are setup instructions, not execution records. The parent integration run generated `requirements.lock.txt` from the supported Python 3.12 environment and reported a successful `pip check`. The parent verified the final regression: 395 Python tests passed in 12.05 seconds, Ruff was clean, npm build/check succeeded, and all 6 real-backend Chromium tests passed in 25.4 seconds. The synthetic benchmark completed. Independent bounded core and engines/frontend/container-configuration reviews reported no vulnerabilities; these are not certification. See [docs/VALIDATION.md](docs/VALIDATION.md) for consolidated evidence.

## Existing checkout and environment

Run from the repository root. If `.venv` already exists, reuse it rather than deleting or replacing it:

```bash
source .venv/bin/activate
python --version
```

Confirm Python 3.12. For a **new** environment only:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install the release lock when available, with a development fallback while integration is ongoing:

```bash
if [ -f requirements.lock.txt ]; then
  python -m pip install -r requirements.lock.txt
else
  python -m pip install -r requirements.txt
fi
npm ci
npm run build
```

`requirements.txt` has version ranges; it is not a fully pinned lock. Docker deliberately uses `requirements.lock.txt` and fails if it is absent. Do not rename the release lock or silently replace it with an unpinned production dependency set.

For a new configuration only (never overwrite the private environment):

```bash
if [ ! -e .env ]; then
  cp .env.example .env
  chmod 600 .env
fi
```

AI works only when explicitly enabled and configured; the default application should be used with `AI_ENABLED=false`. Keep private keys out of shell history, browser code, screenshots, and public repositories.

## Run

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Visit `http://127.0.0.1:8000`. Local `/docs` serves the bundled static OpenAPI viewer without CDN dependencies; it reads `/openapi.json` from the running local server. It is a reference viewer, not an interactive request console. The frontend implementer's verified Chromium suite includes this viewer. Health check:

```bash
curl --fail http://127.0.0.1:8000/api/v1/health
```

Use one worker. Uvicorn CLI arguments control binding; setting `HOST`/`PORT` in `.env` alone does not change this command. The Docker entrypoint explicitly reads the process `PORT` variable.

## Settings

`backend/config.py` reads the root `.env` and environment variables; environment variables take precedence. `.env.example` documents the cap variables matching this configuration; the existing private `.env` is not changed. Names below are uppercase environment names.

| Setting | Local default | Public/cloud effective default |
| --- | --- | --- |
| `APP_ENV` | `local` | Set explicitly to `public` or `cloud` |
| `STORAGE_ROOT` | Repository `storage/` | Same; Docker `/app/storage` |
| `MAX_UPLOAD_MB` | 25 MiB | At most 5 MiB |
| `MAX_ROWS` | 50,000 | At most 10,000 |
| `MAX_COLUMNS` | 100 | At most 50 |
| `MAX_SESSIONS` | 50 | At most 10 |
| `MAX_STORAGE_MB` | 512 MiB | At most 256 MiB |
| `MAX_VERSIONS` | 30 including baseline | 30 |
| `SESSION_TTL_MINUTES` | 60 | 60 |
| `JOB_TIMEOUT_SECONDS` | 120 | 120 |

Public/cloud mode clamps the listed public maxima even if larger values are supplied. Expanded-input limits are 100 MiB local / 30 MiB public, with a maximum expansion ratio of 100. These are application checks, not operating-system memory quotas. The configured timeout is cooperative, not thread cancellation.

| AI setting | Default |
| --- | --- |
| `AI_ENABLED` | `false` |
| `AI_ZERO_COST_MODE` | `true` |
| `OPENROUTER_API_KEY` | Empty |
| `OPENROUTER_MODEL` | `openrouter/free` |
| `AI_REQUEST_TIMEOUT_SECONDS` | 15 (maximum 30) |
| `AI_MAX_RETRIES` | 1 (maximum 1) |
| `AI_CACHE_ENABLED` | `true` |
| `AI_DAILY_REQUEST_LIMIT` | 45 (maximum 45) |

Optional AI settings do not guarantee provider availability or a zero hosting bill. See [security](SECURITY.md) and [deployment](DEPLOYMENT.md).

## Troubleshooting

- Missing browser assets: rerun `npm ci` and `npm run build`; do not substitute CDN scripts for bundled assets.
- HTTP 429 `busy`: wait for the current operation, including any over-deadline ingestion thread, to finish.
- HTTP 409: refresh metadata, obtain current version/revision, and create a new preview.
- HTTP 410: session expired; upload again. Missing/invalid tokens return 404.
- HTTP 413: reduce file size/dimensions, delete an owned dataset, or wait for cleanup.
- Permission error: ensure the process user can write `STORAGE_ROOT`; do not make it globally writable.
- Optional AI unavailable: deterministic analysis remains the primary workflow.

See [DEVELOPMENT.md](DEVELOPMENT.md) for checks and [DEPLOYMENT.md](DEPLOYMENT.md) for container instructions.
