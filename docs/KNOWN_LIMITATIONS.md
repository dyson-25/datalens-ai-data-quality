# Known limitations

For the current 2026-11-14 audit, see [current verification limitations](DATAlENS_KNOWN_LIMITATIONS.md), the [full report](DATAlENS_FULL_VERIFICATION_REPORT.md) and [test matrix](DATAlENS_TEST_MATRIX.md). All 653 automated cases passed; four external/instrumentation scenarios are blocked and seven are untested. Optional AI transport was mocked in this audit; no live provider request occurred.

The sections below retain earlier release limitations and historical external-gate evidence; they are not new provider/container/deployment checks.

## External release gates

- Docker build was attempted but Docker is not installed and no daemon/socket or alternative container engine is available. **Image build remains unverified.**
- No Render account/deployment authorization is available. Configuration is prepared; **no public deployment is claimed**.
- Free-provider availability is external and cannot be guaranteed. An earlier release recorded one successful synthetic OpenRouter request; the 2026-11-14 audit made no live request. Core processing remains functional without AI.

## Deliberate boundaries

- Single server process/worker only. A global processing gate bounds expensive work; busy requests return 429. This is not a multi-tenant high-concurrency service.
- Ingestion runs in a bounded background job; timeout cancellation is cooperative, not process isolation. A stuck native parser can hold the slot until it returns. Other expensive operations are synchronous and bounded by dataset limits, not hard execution deadlines.
- Jobs do not resume after restart. Completed local snapshots survive process restart until TTL expiration; free-host filesystems are ephemeral and can lose all data on restart/redeploy/spindown.
- Session retention is a fixed deadline (60 minutes by default), not an inactivity timeout extended by cleaning or exports. The exports workspace displays the deadline. After expiry the cleanup task removes the stored original and snapshots; an expired row returns 410 before cleanup, while an already removed session returns 404. The browser clears its stale workspace only after confirming session unavailability, and instructs the user to re-upload/reload the source and reapply reviewed changes. A cached v1 label is not proof that the server still retains v1.
- Conservative upload/row/column/memory/storage limits reduce risk but cannot guarantee memory capacity on a shared machine. Large-file streaming, distributed processing and durable cloud datasets are not implemented.
- Dates require explicit user-approved conversion. Leading-zero identifiers and literal null tokens are preserved. Unquoted CSV blanks are null; quoted empty strings remain strings. XLSX formulas are preserved as untrusted text, not evaluated. Mixed Excel scalar columns may use lossless string representations for safe Parquet storage.
- Statistical anomalies are review suggestions, not proven errors. IsolationForest is opt-in and bounded. Tiny planted fixtures do not establish real-world detection accuracy.
- Exported spreadsheets neutralize formula-like text; safe exported text can therefore differ from its underlying snapshot representation. Originals and snapshots remain untouched.
- PDF output uses the browser's print/save-as-PDF workflow on the HTML report, not a server-side PDF renderer. Reference Python/SQL is downloaded, never executed by the application. SQL documents transformations that cannot be translated exactly.
- AI receives only anonymized aggregate counts/types, not column names or records. This is optional external processing, not an offline language model. No paid models or paid fallback are permitted.
- Capability possession grants dataset access. There are no accounts, role-based access control, cross-device token recovery or encrypted-at-rest dataset storage. Use a trusted local machine and HTTPS for authorized public hosting.
- API docs are a locally bundled read-only OpenAPI viewer, not an interactive Swagger request console. Public/cloud `/docs` is disabled; the OpenAPI schema is still available.
- Some dynamic analysis responses use dictionaries; important metadata/profile/job responses and mutating request bodies have explicit Pydantic validation.
- No guarantee of permanently free third-party hosting: provider quotas, terms, spending controls and billing settings remain the account owner's responsibility.
