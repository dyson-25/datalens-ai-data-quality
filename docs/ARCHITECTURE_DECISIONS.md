# Architecture decisions

## Starting constraints
- Reuse the prepared workspace and virtual environment. Never modify the private `.env` or reference PDF.
- Approved baseline: Python 3.12, FastAPI/Pydantic, Pandas/NumPy/PyArrow, SQLite and vanilla JavaScript with locally compiled Tailwind/ECharts.
- Local-first single-process modular monolith; one bounded processing slot avoids overlapping DataFrame memory spikes.
- Original uploads and immutable snapshots remain private; separate random capability tokens authorize every dataset operation.
- Exact statistics and transformations are deterministic. AI is optional, aggregate-only and fails closed on cost uncertainty.
- No real dataset/secret is transmitted to third parties. An optional provider connection test may use only synthetic aggregate context and the configured authentication header.
- Completed 47-page supplementary blueprint reconciliation in BLUEPRINT_COMPARISON.md. Follow master limits and review-only transformations, reject fixed-percentage data deletion, multi-provider fallbacks and unmeasured accuracy/performance claims.
- Frame processing is serialized with one bounded slot. Ingestion is an in-process background job, timed out cooperatively before publishing: Python threads are not forcibly killed. Other bounded processing endpoints return results synchronously. See limitations before public use.
- SQLite transactions publish immutable Parquet snapshots by atomic rename; crash recovery removes unpublished snapshots. Version numbers never reuse committed IDs; new edits after undo branch from active parent and clear redo, retaining explicit restoration of earlier branches. Revisions prevent stale approval even after undo/redo returns to the same version.
- Direct report PDF generation deferred to browser printing of escaped HTML reports; avoid introducing an unverified rendering dependency.
- Official OpenRouter documentation verified the `openrouter/free` router is zero-priced; paid fallback arrays are prohibited. Gateway additionally verifies live catalog pricing and zero-price provider constraints before optional synthetic requests.
