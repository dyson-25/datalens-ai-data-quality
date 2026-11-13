# DataLens blueprint comparison

## Review status and authority

**All 47 pages reviewed before architectural finalization.** The supplied extraction was read from beginning to end (lines 1–2174, including the final page separator), in bounded reads of at most 100 lines. The one truncated response was reread in a smaller overlapping range. The master specification attachment was also read completely (lines 1–1873). This note reconciles requirements; it does **not** certify application implementation, tests, capacity, deployment, or current provider terms.

Sources:

- **Blueprint:** local `docs/reference/Original_DataLens_Blueprint.pdf`; supplied extracted `blueprint.txt`. References below use physical PDF pages and Part II section numbers unless stated otherwise.
- **Master:** attachment `Pasted text #1.txt`, titled “DATALENS — MASTER AUTONOMOUS ENGINEERING, DEVELOPMENT AND RELEASE SPECIFICATION.” References below use its numbered sections.
- **Current review request:** narrows this task to this comparison document and explicitly requires a separate capability token and no raw samples to AI.

Authority: current review constraints govern this task; the master governs the product; the PDF supplies compatible details only. The PDF's “single source of truth” heading does not override the master. Its 47-page count was confirmed using PDF metadata, superseding the master's descriptive “45-page” reference.

### Preservation evidence

- PDF metadata: 47 pages; 709,037 bytes; PDF 1.4; Letter; title beginning “PROJECT MASTER BLUEPRINT: DATALENS”; producer Skia/PDF m159 Google Docs Renderer.
- PDF SHA-256: `4d50aacc7b88f73d76a26608fa35bcad06199b6328369c0cd977ac40275af3ce`.
- The original PDF was only inspected read-only, not edited, renamed, moved, uploaded, staged, or published. No external service was used for this review.
- `.env` was not accessed. Only this comparison document was created. No implementation or other documentation edits were made.
- Public exclusion of the exact PDF path remains a release prerequisite under master §1.6; this scoped review did not inspect or change `.gitignore` and makes no claim that exclusion is currently configured.

## 1. Binding conflict decisions

| Topic | Supplementary proposal | Governing decision |
|---|---|---|
| Runtime and environment | Python 3.11+, a 3.11 image, fresh environment setup (pp. 2, 26, 43–44, 46–47). | **Python 3.12**, using the prepared 3.12.3 environment. Verify dependency/image compatibility; do not recreate the environment or initialize Git. Master §§1, 5, 25. |
| Upload capacity | 50 MB local / 15 MB cloud, preset row/column capacities (pp. 2, 9, 25, 44, 46). | **Initially 25 MB local / 5 MB cloud**, configurable, enforced while streaming. Define row, column, decompressed-size and memory limits independently. Increase only after benchmarks. Master §§7, 20. |
| Anomaly methods | Parametric Z-score, IQR, MAD, Isolation Forest and LOF, with automatic skewness routing (pp. 13–14, 22, 27, 34, 40–41). | **IQR and modified Z-score using MAD; optional, resource-gated Isolation Forest only.** No ordinary Z-score detector or LOF. Do not run every algorithm automatically. Master §10. |
| Error classification | Very large MAD scores treated as confirmed/probable data errors; domain meaning inferred from headers (pp. 11–14). | A statistical extreme is not proof of error. Confirm rule violations only against explicit domain constraints; keep statistical, multivariate and suspicious/unverified labels distinct. Master §§9–10. |
| Cleaning policy | Fixed missingness cutoffs prioritize row/column dropping; inferred dates may be coerced; forward fill proposed for time series (pp. 14–15). | **No automatic dropping or silent coercion.** User-selected operations require explained impact, preview and approval. No percentage cutoff establishes that data is dispensable. Master §§11–12. |
| AI providers | OpenRouter plus Ollama; future LiteLLM/direct-provider fallback (pp. 3–5, 18–25, 28, 45–47). | Initial AI integration is asynchronous HTTPX → OpenRouter. **No Ollama, LOF or paid fallback**, and no speculative multi-provider infrastructure. Unavailable AI falls back to deterministic explanations. Master §§5, 13. |
| Free routing | Hard-coded `:free` whitelist and fixed provider/model/quota claims (pp. 4, 24–25). | Prefer `openrouter/free` where supported; verify current official routing and zero-price constraints before use. A suffix or historical catalogue is not sufficient proof. Fail closed if zero cost cannot be verified. Master §13. |
| AI configuration | 12-second timeout; per-model retry/fallback chains and alternative variable names (p. 25). | Follow the master's consistent configuration: 15-second timeout, one configured retry, daily local limit initially 45, cache and usage accounting. Retry attempts count toward local usage; avoid multiplying retries across hidden fallback chains. Preserve existing private settings. Master §§1.7, 13. |
| AI disclosure | Up to three truncated example strings and column names in prompts (p. 38), despite other pages saying no sensitive raw rows. | **No raw samples, records, full files or value excerpts to AI.** Use a separate allowlisted aggregate/anonymized context, not the full UI profile. Remove identifying headers and sensitive category values too. The master's possible authorized-example extension is not enabled by this review request. Master §13 plus current request. |
| Authorization | Dataset UUID presented as the public capability (p. 38). | Dataset UUID is an identifier, **not authorization**. Require a separately generated capability token and ownership checks on every dataset-dependent operation, job, preview and download. Master §§17–19 plus current request. |
| Jobs and concurrency | `BackgroundTasks`/worker pool, automatic ML scans, `n_jobs=-1`, ten concurrent requests (pp. 14, 23, 44). | Bounded single-process job manager; **initially one public processing job**. Track status, timeout, failures, expiration and restart interruption. HTTP connection limits are not processing admission control. Avoid unconstrained ML threads. Master §§6, 20, 25. |
| Version history | Undo by decrementing a version number; keep baseline plus last ten snapshots (pp. 15–16). | Atomic, immutable snapshots; stable row IDs; explicit restoration/redo and branch semantics. Never overwrite an old snapshot after undo or prune a promised restore target silently. Coordinate mutations and retention. Master §12. |
| Preview correctness | Some descriptions permit slice/sample-based processing while promising exact changes (pp. 7, 15, 23). | Preview and apply share the same validated operation on the same source version. Compute actual impact; only displayed diff rows are sampled/bounded. Reject stale previews instead of applying against a different version unnoticed. Master §12. |
| Export safety | Formula sanitization described as optional or toggleable on some pages (pp. 17, 34), default-on elsewhere. | Sanitize both CSV and XLSX at export without changing original/internal values. Initial safe exports must not rely on a user opting into protection. Preserve legitimate numeric types. Master §19. |
| UI scope | Twelve panels and ten navigation entries (pp. 28, 33–34). | Organize compatible panels within the master's **five integrated workspaces**, not twelve independent applications/pages. Master §16. |
| Required versus optional | PDF reports and live Render deployment presented as unconditional completion gates (p. 47). | CSV/XLSX, JSON/HTML and reference code remain required; PDF is conditional on reliability. Public deployment depends on authorization and actual verification. Optional does not mean a dead button. Master §§16, 22, 25, 28. |
| Delivery process | Ten phases, one phase per new prompt, fixed file counts, destructive checkout recovery (pp. 40–43). | Follow the master's twelve-phase dependency-aware lifecycle with continuing work and verified milestones. No destructive recovery, repeated setup or need for a new prompt per phase. This review itself authorizes documentation only. Master §§24, 26–30. |
| Performance and accuracy | Subsecond previews, fixed memory savings/RSS, guaranteed speed and benchmark accuracy targets (pp. 9, 15, 18–19, 23, 30, 39–41, 45–47). | Treat numbers as unverified proposals, not capacity or quality claims. Report measured fixture results with environment and scope. No promised score improvement, universal MAD superiority or population accuracy. Master §§3, 20–22. |

## 2. Compatible requirements retained

“Retained” means a requirement or useful design input for implementation, not a claim it already exists.

### Product and end-to-end workflow

Retain the local-first, offline deterministic workbench, optional AI explanations, explicit human control and auditable transformations (pp. 1–3; master §§2–6). The blueprint's expanded workflow usefully makes parser confirmation, dependency ordering, post-change revalidation, code export and report export explicit (pp. 5–8).

The required sequence is upload → inspect/confirm parser and worksheet → baseline → profile/findings → anomaly inspection → recommendations → preview → approval → new version → revalidation → restore/reset or export. Recompute dependent findings and invalidate stale recommendations after changes; do not simply mark an old issue resolved because its suggested operation ran.

### Ingestion and preservation

Retain streaming size enforcement, extension/content checks, bounded sniffing, encoding/delimiter detection with visible overrides, adjustable header selection, duplicate-header normalization and worksheet selection (pp. 6, 8–9, 37–38; master §7).

- CSV and XLSX are initial formats; reject unsupported legacy and macro-enabled workbooks clearly.
- A 64 KB sniff/upload chunk is a reasonable starting implementation detail, not a required universal optimum. An uncertain delimiter/header guess must remain adjustable.
- Keep an original-to-normalized header mapping; normalization must not erase which source column was which.
- Detect empty, malformed and oversized cells/files; do not silently skip bad rows.
- Inspect XLSX archive members, total expanded size and expansion ratio before parsing; use safe XML handling. The PDF's 150 MB/50:1 thresholds need resource validation, not blind adoption.
- Handle formulas and missing cached formula values explicitly. Workbook read-only mode reduces parser overhead but does not eliminate full DataFrame memory costs.
- Preserve source values when establishing `v0`; avoid ingestion defaults that silently replace every ambiguous null token, numeric identifier or date-like string. Record inference uncertainty and let approved cleaning perform conversions.
- UUID-based storage paths, bounded parsing and PyArrow/Parquet are retained; stable internal row identity must survive filtering and conversion.

### Profiling and quality detection

Retain version-keyed profile caches; dataset dimensions, missingness, duplicate counts, type breakdown and memory metrics; numeric statistics and histograms; categorical frequencies/lengths; and date ranges/validity (pp. 9–13; master §§8–9). Keep storage dtype separate from inferred semantic type. Serialize non-finite and missing values safely rather than emitting invalid JSON.

Useful blueprint details include representative local-only inspection values, explicit distinct-count denominators, rare-category summaries, top categories plus an “Other” bucket, and whitespace/case variants. Histogram bin counts and top-k limits should be bounded and documented, not treated as compulsory constants.

Retain all master initial detection categories: missing values, empty strings, whitespace, exact duplicates, duplicate columns, numeric strings/conversion failures, invalid/mixed dates, category casing/possible typos, constants, sentinels, email-like/phone-like anomalies, explicit-domain negative values and mixed formats.

- Findings carry stable row references, counts, severity, method, explanation, uncertainty and proposed action.
- Null/sentinel lists are candidates for user selection, not universally erroneous values.
- Hashing can shortlist duplicate columns; verify equality before reporting an exact duplicate. Hash equality alone is insufficient.
- RapidFuzz suggestions remain heuristic and approval-only. Bound unique-category comparisons (the PDF suggests a 200-category cap) to avoid quadratic work on free text.
- The PDF's 80% parseability, 88% fuzzy similarity, 1% rarity and phone-length thresholds are candidate heuristics, not universal rules or proof of validity.
- Email syntax does not establish ownership; phone formatting is region-dependent. Header names alone do not establish business constraints.
- Keep anomalies outside the deterministic issue inventory. The PDF alternates between 14, 16 and 17 rules; implement the master's named requirements rather than reproducing its inconsistent counts.

### Anomaly analysis

Retain explainable IQR fences and robust MAD scoring with visible parameters, values and row references (pp. 13–14; master §10). Cover insufficient observations, non-finite inputs, constants, zero IQR/MAD and skewed distributions; define and test skip/degenerate behavior rather than dividing by zero or silently selecting a prohibited detector.

Isolation Forest is optional and on demand when suitable numeric features and resource budgets permit. Exclude identifiers and arbitrary category encodings; record selected features, reproducible randomness and any temporary preprocessing. Imputation for the model must not mutate the dataset or masquerade as a user-approved cleaning action. Scores express unusualness, not correctness or causal explanations.

### Recommendations, transformations and history

Retain pure parameterized operations shared by preview/apply; deterministic recommendation reasons; explicit benefit, data-loss and trade-off descriptions; and versioned audit metadata (pp. 14–16, 29–32; master §§11–12).

Initial operations follow the master: whitespace trimming; selected null normalization; selected duplicate removal; numeric/date conversion; numeric/categorical fills; selected column removal; text case changes; approved category maps; infinity handling; and approved selected-outlier handling. Do not implement a universal automatic “fix all.”

Preview must show accurate affected rows/cells, additions/removals, before/after values and metric changes while keeping the active version untouched. Show a bounded row sample without implying it is the full affected set. Count null-to-null comparisons correctly and align by stable internal IDs, not changing DataFrame positions.

Apply must revalidate the operation and source version, write a new snapshot atomically, persist audit metadata and update the active pointer safely. Define failure recovery across filesystem writes and SQLite transactions. Use monotonically unique snapshot identities plus parent relationships so new work after undo cannot overwrite a former branch. Preserve `v0`; expose which retained versions can actually be restored. Never export the internal row-ID field.

### Storage, API and job management

Retain SQLite metadata and on-disk Parquet rather than raw tables in SQLite or many permanent in-memory DataFrames (pp. 21–23, 26–32; master §§6, 17–18). Use the master's `storage/sessions/<dataset_id>/{original,snapshots,reports}/` organization. SQLite WAL is useful, but not a substitute for foreign keys, indexes, transactions and serialized conflicting updates.

Retain logical entities for datasets, versioned profiles/findings/recommendations, transformations, AI usage/cache and optional export audit metadata. Add explicit job state and separate session authorization; the PDF's seven-table diagram is not a complete approved schema.

Retain a consistent versioned REST API with Pydantic models, structured errors, bounded/paginated data and appropriate status codes. The PDF's 18 endpoints are a capability starting point, not an exact contract: include inspection, jobs, deletion, AI availability and version restoration as required without duplicate endpoints. Protect profiles, findings, recommendations, job results, code and report downloads as well as mutations.

Retain inactivity expiration and the explicit “delete session/wipe data” action (pp. 23, 32, 38). Cleanup must coordinate with active jobs/mutations and remove associated files, metadata and session-specific caches. Do not promise uninterrupted jobs or persistent free-host storage. TTL duration, sweep frequency and snapshot counts remain documented configurable policies.

### AI, reference code and presentation

Retain non-blocking AI enrichment, Pydantic response validation, short timeouts, limited retry, bounded cache, usage tracking, quota feedback and deterministic fallback (pp. 23–25; master §§13–14). Prompts, outputs and dataset-derived labels are untrusted; delimiters alone do not guarantee protection. AI cannot select or execute arbitrary operations.

Use a dedicated aggregate context schema so local profile samples/category labels cannot leak through generic serialization. Scope caches appropriately and include task/template version and relevant context identity; do not expose one session's response through another. Display whether an explanation is deterministic, AI-generated or cached. Current provider documentation must be verified during implementation; no live connection test was performed for this note.

Retain deterministic Python and SQL templates for approved operations and the active cleaning pipeline, with copy/download and “reference only; not executed” labels (pp. 16–17, 34). Escape Python literals and SQL identifiers/values correctly. Declare the SQL dialect and explicitly flag unsupported transformations; do not call a mixture of ANSI and DuckDB syntax universally portable. An import/export script must reflect actual parser settings and active history, not always assume a default CSV source. A DuckDB SQL dialect does not require adding a DuckDB runtime dependency.

Retain locally bundled Tailwind/ECharts, accessible dark/light themes, consistent numeric typography, loading/error/empty states, confirmation dialogs, issue filters and linked column inspection (pp. 16–17, 32–34; master §§15–16). Use safe DOM text rendering for all dataset-derived content.

Charts must use real backend results: missingness, histograms, box plots, frequencies, suitable correlations, anomalies and before/after comparisons. Bound scatter/matrix payloads and disclose sampling. Tukey whiskers must use the selected fence convention, not incorrectly label the raw minimum/maximum as whiskers when outliers exist. “No findings under these checks” is preferable to “100% clean.”

### Reports, verification and release

Retain sanitized CSV/XLSX; machine-readable JSON audit summaries; offline/self-contained HTML; and reliable optional PDF reports (pp. 17, 34, 37–41; master §§16, 21–23). Reports should identify source/current versions, before/after profiles, applied history, resolved/unresolved findings and remaining uncertainty. Report/download data stays within the session's access boundary.

Retain deterministic synthetic fixtures for clean data, disguised missingness, duplicate rows/columns, mixed numeric/date formats, category variants, skewed anomalies, malformed files and multi-sheet workbooks (pp. 29, 38–39). Use seeded size-scaled benchmark generation rather than committing private or large runtime datasets.

Test exact formulas and fixtures; original/baseline preservation; preview/apply equivalence; undo/restoration/reset; branching and concurrent changes; interrupted writes/jobs; ownership and expiry; export round trips/formula safety; path and DOM safety; AI-disabled operation, failures and zero-price guards; and the complete browser workflow. Evaluate heuristic precision/recall only against stated fixture ground truth. Report actual timings, absolute peak memory and storage consumption, not just a favorable memory delta.

Retain one-worker deployment as the initial configuration, dynamic ports, health checks, bundled assets, synthetic demo datasets and explicit ephemeral-storage notices (pp. 43–47; master §25). Verify current Render terms before deployment; do not assume older RAM, CPU, sleeping or quota statements remain true. Keep secrets, virtual environments, private PDF and runtime storage out of public artifacts and images. Screenshots, demonstrations and release status must reflect verified behavior.

## 3. Material deferred or conditional items

These are explicit dispositions, not permission to postpone master-required features.

| Blueprint idea | Disposition and reason | Reconsideration condition |
|---|---|---|
| Analytics/classification/regression intent, target selection, leakage and imbalance checks (pp. 5–6) | Defer the ML-readiness workflow; it requires user-defined target semantics and checks beyond the initial quality product. Do not infer target leakage from column names. | Core acceptance complete; explicit domain contract and labeled tests. |
| Inferred primary-key collisions and automatic ID irrelevance judgments (pp. 10, 12–13) | Defer key-uniqueness business rules until users can select keys. Retain ID identification for inspection and exclusion from ML; never automatically drop identifiers. | Explicit key configuration and composite-key/null semantics. |
| Generic delimited `.txt` and TSV (p. 8) | CSV/XLSX required. TSV is a low-complexity optional extension; arbitrary `.txt` is not an initial acceptance requirement. | Reuse validated parsing and test content/extension behavior. |
| Forward fill, missing indicators and automatic date/sentinel assumptions (pp. 9–15) | Defer additional operations/contextual checks beyond master's initial set. Forward fill needs ordering/group semantics; sentinels and future dates are domain-dependent. | Explicit parameters, loss preview and corresponding tests. |
| Fixed five-component weighted health score including outlier health (pp. 6, 9, 33) | Retain transparent dimension summaries and before/after comparison; defer adopting the exact 30/25/20/15/10 weighting. Penalizing valid extremes can reward unnecessary clipping. | Document applicability, denominators, overlap and weights; keep anomaly burden distinct from correctness. No mandatory score increase after every operation. |
| KDE overlays and full missingness matrices (pp. 16–17, 45) | Optional visual enhancements. Histograms and missingness bars satisfy core visualization needs without extra cost/clutter. | Meaningful interpretation, bounded computation and UI tests. |
| Both Pearson and Spearman over every numeric column (pp. 17, 30) | Suitable correlation visualization retained; exhaustive dual matrices deferred. Bound dimensions, exclude unsuitable/constant data, disclose missingness treatment. | Resource benchmarks and user-selectable analysis. |
| fpdf2-based executive reports (pp. 17, 20, 41) | Conditional, not guaranteed merely by selecting a library. JSON and HTML cannot depend on PDF availability. | Validated Unicode/fonts, pagination, chart/table output and actual license/dependency review. |
| Exactly ten retained snapshots, 60-minute cloud/24-hour local TTL, 15-minute sweep (pp. 16, 23, 32) | Retain retention and expiration capability, defer these exact constants. They must not break active work or advertised restoration. | Measured storage budgets and explicit UI retention contract. |
| Hugging Face mirror or larger-dataset hosting (p. 43) | Defer secondary deployment; one verified local build and optional Render demo are enough initially. No larger upload promises. | Concrete hosting need, current terms and measured capacity. |
| Custom fonts, animation/GIF demos and advanced UI polish (pp. 32–34, 44–45) | Core accessibility/themes/states retained. Custom font packaging and promotional polish are secondary to working interactions. | Locally bundled licensed assets and real application captures. |
| Multi-provider abstraction, Ollama, LiteLLM, direct Groq/Gemini and paid fallback (pp. 3–5, 19, 22–25) | **Excluded from this release, not an implicit next milestone.** They add unneeded complexity or violate the requested boundary. | Requires a new explicit scope decision; paid fallback remains forbidden. |
| LOF, ordinary Z-score and automatic algorithm fan-out (pp. 13–14, 22, 34) | **Excluded**, not deferred implementation obligations. | A new approved algorithm scope would be required. |

## 4. All-page review ledger

Page boundaries were checked against the extraction's form-feed separators and the PDF's 47-page metadata. Diagram source and wireframe text were included in the review. Some multi-column algorithm-table formulas are fragmented in extraction; decisions use the complete surrounding prose and master §10 rather than treating broken table fragments as authoritative mathematics. This is an all-page **text** review, not a claim of rendering every PDF page.

| PDF page | Extracted lines | Reviewed subject and disposition |
|---|---:|---|
| 1 | 1–37 | Product problem, users and deterministic/non-destructive value proposition retained. |
| 2 | 38–80 | Stack, costs and memory risks; supersede runtime, caps, algorithms and providers. |
| 3 | 81–123 | Core laws and local-LLM discussion; retain laws, exclude Ollama. |
| 4 | 124–170 | Local model hardware and free-tier assertions; exclude local models, reverify external claims. |
| 5 | 171–216 | Cost table and workflow additions; retain parser/revalidation needs, defer ML intent. |
| 6 | 217–263 | Upload, sniff, ingestion, context and profiling steps; retain bounded confirmation flow. |
| 7 | 264–310 | Inspector, findings, anomalies, recommendations and approval; retain with exact previews. |
| 8 | 311–356 | Revalidation, restoration, exports and parser details; retain master's stronger history semantics. |
| 9 | 357–402 | Limits and profiling metrics; replace upload caps and defer fixed score weights. |
| 10 | 403–448 | Missingness, duplicates, type and date detection; retain with explicit uncertainty. |
| 11 | 449–495 | Categorical, whitespace, numeric-domain, constant and sentinel checks; retain safeguards. |
| 12 | 496–542 | Email, phone, mixed-format, anomaly and identifier issues; separate heuristic findings. |
| 13 | 543–589 | Algorithm comparison; retain only IQR/MAD and optional Isolation Forest. |
| 14 | 590–637 | LOF, error/extreme classification and recommendation thresholds; reject unsafe defaults. |
| 15 | 638–685 | Cleaning matrix and preview data; retain explicit approval, loss reporting and exact diff. |
| 16 | 686–733 | Apply/undo retention, code templates and chart choices; strengthen atomic history. |
| 17 | 734–781 | Charts and CSV/XLSX/JSON/HTML/PDF exports; retain safety, condition PDF. |
| 18 | 782–828 | Engine/database/gateway alternatives; retain simple Pandas/SQLite/HTTPX stack. |
| 19 | 829–875 | Gateway comparison and versions; reject speculative adapters, reverify compatibility. |
| 20 | 876–922 | Statistical/reporting/AI dependency details; remove excluded methods/providers. |
| 21 | 923–968 | Frontend/testing/deployment stack and architecture diagram; retain modular monolith. |
| 22 | 969–1016 | Engine/gateway/storage diagram and edges; retain boundaries, simplify AI. |
| 23 | 1017–1064 | Execution model, jobs, cleanup and AI responsibilities; require bounded job manager. |
| 24 | 1065–1111 | Free-routing guards, quotas, cache and sequence start; use current zero-price checks. |
| 25 | 1112–1159 | Fallback sequence and configuration; no Ollama, no raw data, use master defaults. |
| 26 | 1160–1206 | Repository/root/config/API tree; reuse existing workspace, don't reproduce scaffolding blindly. |
| 27 | 1207–1254 | Ingestion/profiling/quality/anomaly/cleaning module tree; retain responsibilities not excluded features. |
| 28 | 1255–1302 | Reports, AI, utilities and frontend tree; remove local-provider adapter, use five workspaces. |
| 29 | 1303–1348 | Fixtures, docs, tests and module responsibilities; retain shared operation path and focused tests. |
| 30 | 1349–1394 | Hybrid storage and dataset/profile ER entities; retain versioned metadata, reject speed claims. |
| 31 | 1395–1442 | Finding/recommendation/transformation ER entities; retain audit data with stable IDs. |
| 32 | 1443–1489 | AI usage/cache, deletion/TTL and design tokens; retain privacy-aware cleanup and theme. |
| 33 | 1490–1537 | Full ASCII workbench wireframe and first panels; consolidate into integrated workspaces. |
| 34 | 1538–1583 | Inspector/lab/cleaning/history/export panels and states; remove prohibited controls and certainty claims. |
| 35 | 1584–1630 | Health/upload/ingest/profile/column endpoint inventory; retain capabilities, add authorization. |
| 36 | 1631–1677 | Issues/anomalies/recommendations/preview/apply/undo/reset APIs; strengthen version and job contracts. |
| 37 | 1678–1723 | History/AI/export APIs and file/archive defenses; retain bounded protected operations. |
| 38 | 1724–1769 | Formula/path/XSS/AI/session security and tests; reject raw samples and UUID-only authorization. |
| 39 | 1770–1816 | Browser tests, eight fixture types and quantitative goals; retain measured fixture-based evidence. |
| 40 | 1817–1863 | Foundation through quality roadmap; map to master phases and conservative limits. |
| 41 | 1864–1911 | Anomalies through frontend roadmap; exclude LOF/Z-score/local models, retain regression gates. |
| 42 | 1912–1955 | QA/release and agent coordination; retain single integrator, reject destructive recovery/prompt gating. |
| 43 | 1956–2002 | Local setup and hosting alternatives; reuse environment, defer mirror, verify current terms. |
| 44 | 2003–2049 | Container, documentation and demonstration strategy; Python 3.12, 5 MB cloud, truthful evidence. |
| 45 | 2050–2090 | Demonstration advice and full feature compendium; apply all earlier reconciliations again. |
| 46 | 2091–2131 | Reference index, security checklist and deployment recap; preserve privacy and replace old limits. |
| 47 | 2132–2173 | Resource/cost claims, definition of done and first milestone; reject invented measurements and fresh setup. |

## 5. Architectural finalization handoff

The all-page review prerequisite is satisfied. Final implementation contracts must still explicitly define:

1. Separate capability-token lifecycle, ownership checks, expiry and deletion coverage.
2. Stable internal row IDs; version parentage; stale-preview rejection; atomic apply/recovery; retention and restore behavior.
3. 25/5 MB byte conventions and limits, decompression/cell/shape budgets, one-job public admission and bounded response sizes.
4. IQR/MAD degeneracy policies, optional Isolation Forest eligibility and explicit domain-rule configuration.
5. Aggregate-only AI context, verified zero-cost OpenRouter routing, retry/quota accounting and deterministic fallback.
6. Initial operation contracts, SQL dialect/limitations, safe CSV/XLSX export and accurate report/version linkage.
7. Master-required acceptance tests and measured benchmarks; no unsupported score, speed or deployment claims.

These decisions should feed the architecture/limitations/status documents during implementation. Those files were intentionally not edited in this documentation-only review.
