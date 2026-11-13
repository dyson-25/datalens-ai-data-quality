# Security and privacy

DataLens is a temporary data workbench, not a certified secure document vault or a multi-tenant identity platform. On 2026-11-13, the parent confirmed completion of both independent bounded code reviews: core, and engines/frontend/container configuration. Neither reported vulnerabilities. These reviews are not penetration tests or certification; absence of findings is not proof that vulnerabilities are absent. No production-readiness guarantee is made. See the consolidated [validation evidence](docs/VALIDATION.md).

## Dataset capabilities, not permanent accounts

Every upload/sample creates a separate private token. Supply it through `X-Session-Token` on that dataset's endpoints, including jobs and exports. The dataset UUID is not enough. Tokens are high-entropy bearer capabilities; anyone possessing one can access and delete that dataset until expiry. The database stores a SHA-256 hash and authorization compares hashes in constant time.

Do not put tokens in URLs, analytics, screenshots, logs or shared links. Keep browser capabilities private; there is no password reset, account recovery or server-side user identity. Missing/invalid tokens return 404 rather than disclosing dataset existence. Use HTTPS outside localhost. Client compromise, browser extensions or an exposed token defeat capability secrecy.

## Data retention and local trust

Original files, immutable snapshots, metadata and profile caches can all contain sensitive information. Storage is capped and expires, but expiry is not instantaneous secure erasure: cleanup waits for a free processing slot, and deletion does not sanitize storage media or remove external copies/backups. Operators and host administrators can access filesystem contents. Application-level encryption at rest is not provided.

Local storage may survive an ordinary process restart; it is still not a durable product promise. On Render free services it is lost on spin-down, restart or redeploy. Export before expiry. There are no permanent accounts or guarantees of data restoration.

## Private files and build boundary

Never publish or embed the existing private `.env`, virtual environment, local uploaded datasets, local reports, or reference PDFs. Use `.env.example` only as a blank configuration template. The Docker build context is allowlisted and explicitly excludes environment files, PDFs, `.git`, `.venv`, storage, node_modules, caches and reports. The runtime image copies only backend code, built browser assets, synthetic samples and its dependency lock. It does not use `COPY . .`.

Before publishing a repository or image, review the actual tracked files and image contents. `.dockerignore` protects Docker context, not Git publication; `.gitignore` does not remove an already-tracked secret. Rotate any exposed provider key or dataset capability by the appropriate provider/deletion workflow. Do not attach raw datasets or private PDFs to public issue reports.

## Input and resource controls

The application checks body/upload size, dimensions, expanded-file size, expansion ratio, session count, version count and storage capacity. Public/cloud settings use smaller caps. UUID/path validation restricts dataset storage paths. Public API traffic has a process-local request limiter; reverse proxies can affect client attribution. These are defensive limits, not a guarantee against every resource-exhaustion input.

Run exactly one Uvicorn worker and one instance. The ingestion timeout is cooperative: Python cannot forcibly kill the worker thread. The slot remains held until thread exit, and an over-deadline snapshot is not published. Peak parsing memory, long-running native code and host termination remain risks. Use only non-sensitive synthetic samples on a public demonstration deployment.

## Output boundary

CSV/XLSX export contracts neutralize formula-leading strings in cells **and headers**. HTML reports escape untrusted content. Browser Content Security Policy favors local assets and forbids embedding; API responses use `Cache-Control: no-store`. These controls require regression coverage and do not substitute for reviewing exported data or reference code. Avoid importing exported files into a less-trusted application without inspection.

Generated Python/SQL is never executed by the server. SQL is a PostgreSQL reference dialect, not an arbitrary database query gateway. AI output cannot approve or apply transformations; an explicit reviewed preview and current revision are required.

## Optional AI disclosure

AI is disabled by default and in `render.yaml`. Enabling it permits outbound requests to OpenRouter. Only a restricted aggregate summary may leave the service: **no raw rows, cell samples, common-value labels, filenames or column names**. Aggregate statistics can still be sensitive; absence of raw data is not formal anonymization or differential privacy. Enable AI only with authorization for aggregate disclosure and after reviewing provider policies.

On 2026-11-13, the parent integration run verified a real OpenRouter connection with minimal synthetic aggregates only (`openrouter/free`, `source:"ai"`, `reason:null`, explanation present). No raw data or credentials were exposed. This verifies that one connection, not continuing availability or complete privacy-test coverage; detailed evidence remains pending in `docs/VALIDATION.md`.

Keys remain server-side. `AI_ZERO_COST_MODE=true`, model restrictions, quotas, caching, request timeouts and limited retries are application controls, not a guarantee that a provider or host cannot charge. Keep AI disabled when cost or disclosure is unacceptable. There is no paid fallback promised here, and provider availability is not guaranteed.

## Reporting a concern

Do not publish exploit details together with secrets or user data. Use the repository owner's private reporting channel if available; no unverified contact address is supplied here. Provide a minimal synthetic reproduction, affected version, expected/actual behavior and redacted logs. Evidence should not contain capabilities, `.env` contents or private PDFs.
