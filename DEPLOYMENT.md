# Deployment

## Current status

The Dockerfile and optional Render blueprint are configuration artifacts, **not proof of a successful build or deployment**. The parent explicitly attempted Docker build; it exited **127 because `docker` was not found**. `gh` and deployment authentication are also unavailable. No image build, live deployment URL or container smoke-test success is asserted.

The parent verified the final release regression: **395 pytest tests passed in 12.05 seconds**, Ruff was clean, `npm run build` and `npm run check` succeeded, and **6 real-backend Chromium tests passed in 25.4 seconds**. A synthetic local benchmark and six actual synthetic screenshots are recorded. Independent bounded core and engines/frontend/container-configuration security reviews reported no vulnerabilities; this is not certification. These are not container-execution or Render-host results. **Git push is still pending**, and authenticated deployment remains blocked. See [docs/VALIDATION.md](docs/VALIDATION.md).

The release owner generated `requirements.lock.txt` from the supported Python 3.12 environment and reported a successful `pip check`. The Dockerfile requires this pinned file and intentionally fails if it is absent; it does not silently use the ranged `requirements.txt`. Dependency resolution is not a container-build result. For local-only setup, [INSTALLATION.md](INSTALLATION.md) documents a development fallback.

## Image design

- Stage 1: `node:22-bookworm-slim`, `npm ci`, then the existing `npm run build` script. Generated Tailwind CSS and local ECharts assets include their license.
- Runtime: `python:3.12-slim`, `pip install -r requirements.lock.txt`.
- Explicit copies: backend, compiled/browser runtime assets (including `api-docs.html` and `api-docs.js` for the bundled OpenAPI viewer), synthetic sample datasets and the dependency lock. No whole-repository runtime copy.
- Nonroot UID/GID 10001, with writable mode-0700 `/app/storage` and `/app/storage/tmp`. Temporary processing uses that storage-backed directory.
- Shell `exec` launches `uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1`. Render can supply `PORT`; local default is 8000.
- Native CPU pools default to one thread via `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1` and `MKL_NUM_THREADS=1`, reducing oversubscription on shared/local/free hosts. These library settings are not operating-system CPU quotas or hard ingestion deadlines.
- AI disabled and public mode enabled by default. No separate database, paid disk, Redis or Node runtime service.

The image uses major-version base tags, not immutable image digests. A pinned Python lock alone does not make every build byte-for-byte reproducible. Review dependency/base-image updates and validate the resulting artifact.

`.dockerignore` allowlists required build inputs and excludes `.env`/variants, `.venv`, `.git`, all PDF filenames (case-insensitive extension pattern), storage, reports, caches and node_modules. Existing private environment files and reference PDFs must not be copied into Docker, repository releases, screenshots, or public artifacts. Docker exclusions do not protect Git publication: inspect tracked files separately.

## Local container verification (build blocked; runtime unverified)

In an environment with Docker, from the project root:

```bash
test -f requirements.lock.txt
docker build -t datalens:local .
docker run --rm --name datalens-local -p 8000:8000 \
  -e APP_ENV=public -e AI_ENABLED=false datalens:local
```

In another terminal:

```bash
curl --fail http://127.0.0.1:8000/api/v1/health
```

Open the browser, ingest a synthetic sample, review/apply one operation, restore an earlier version, export, and delete. Health alone does not validate these features. Stop only the named verification container when finished:

```bash
docker stop datalens-local
```

To check dynamic port binding, repeat with `-e PORT=8080 -p 8080:8080` and request port 8080. Do not combine the new mapping with the old `-p` flag. Inspect the final image for prohibited files and confirm the process runs as UID 10001. A host bind mount needs write permissions for that UID and a writable `tmp/` subdirectory; no volume is mounted by the example or Render blueprint. Container replacement loses unmounted state.

## Optional Render free blueprint

1. Review all publication inputs; exclude private `.env`, PDFs, storage and credentials from the repository. Ensure the Python and npm locks and runtime frontend sources are present.
2. Authenticate to Render separately and connect an authorized repository. No credentials are embedded in `render.yaml`.
3. Create a Blueprint from `render.yaml`. Inspect the preview: exactly one Docker web service, `plan: free`, one instance, **no databases/disks/paid resources**.
4. Leave `APP_ENV=public`, `AI_ENABLED=false`, `AI_ZERO_COST_MODE=true`. Do not upload `.env` or add a provider key just to run the core workbench.
5. Review billing/spend controls before deploying. Render supplies `PORT`; health path is `/api/v1/health`.
6. After an actual deployment, check health and the complete synthetic-data workflow. Record the real URL, commands and results in `docs/VALIDATION.md`. Do not call a configuration-only change a deployment.

The blueprint is optional and should not be used as a production durability promise.

## Verified hosting-policy source, not verified deployment

[Render's official free-service documentation](https://render.com/docs/free), retrieved during preparation on 2026-11-13, states:

| Free-service behavior | Operational consequence |
| --- | --- |
| Spins down after 15 minutes without inbound traffic | Expect idle interruptions; do not promise always-on availability |
| Wake-up takes about one minute | First request can show Render's loading page |
| Ephemeral filesystem lost on redeploy, restart **and spin-down** | Uploads, SQLite, snapshots, cached profiles and tokens' backing metadata disappear |
| 750 free instance hours per workspace/calendar month, shared across free services | Other services consume the allowance; exhausted hours suspend services until next month |
| Outbound bandwidth and build pipeline included usage is limited | Supplementary usage can be billed if a payment method is present |
| Free services cannot attach persistent disks | This blueprint supplies no durable storage |

Without a payment method, excess outbound usage instead suspends free services; exhausted build minutes without a payment method or after reaching the build spend limit disable new builds. With a payment method, outbound/build overages can bill. Review current limits in Render's dashboard, set available build spending limits, and avoid adding a payment method if suspension rather than overage billing is required. **“Free plan” and `AI_ZERO_COST_MODE` are not a universal no-spending guarantee.** Policies can change: reread the linked official page before deployment. Do not use keep-alive traffic to imply free production uptime.

## Runtime limitations and recovery

One worker/instance is mandatory. The in-process semaphore and single ingestion executor are not distributed coordination. Ingestion timeout cannot kill a thread: the slot stays occupied until exit, no timed-out snapshot is published, and graceful shutdown may wait. Application size caps are not hard peak-RAM limits; the host may terminate work.

Storage defaults in the blueprint: 5 MiB uploads, 10,000 rows, 50 columns, 10 datasets, 256 MiB storage, 60-minute dataset expiry, 120-second cooperative ingestion timeout. Profiles are cached per immutable version; they are just as ephemeral as the source. Expired data is cleaned when the processing slot is available.

There are no permanent accounts. Each dataset's separate capability header is required for requests; lost tokens or lost storage require re-upload. Export before leaving the app. Do not store sensitive data on a public demo. Never scale up workers as a workaround for a blocked ingestion thread.

## Release checklist

- [x] Pinned `requirements.lock.txt` generated under Python 3.12; `pip check` succeeded.
- [x] Parent verified 395 Python tests in 12.05 seconds, clean Ruff checks and the synthetic benchmark.
- [x] Parent verified build/syntax checks and 6 real-backend Chromium tests in 25.4 seconds; six synthetic screenshots exist.
- [x] Independent bounded core and engines/frontend/container-configuration reviews completed without reported vulnerabilities.
- [ ] Git push completed and remote publication verified.
- [ ] Node 22 build, final image build and nonroot runtime smoke test executed.
- [ ] Private `.env`, PDFs, storage and reports absent from publication and image.
- [ ] Dynamic `PORT`, health route and end-to-end synthetic workflow verified.
- [ ] Actual Render billing controls and free plan confirmed by an authenticated operator.
- [ ] Actual deployment outcome and remaining limitations recorded in `docs/VALIDATION.md`.

Verified dependency/backend/browser results and completed bounded reviews are checked. Git push and successful container/deployment execution remain pending; the Docker build attempt failed with exit 127 because Docker was unavailable. Render authentication is unavailable.
