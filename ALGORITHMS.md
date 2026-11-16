# Algorithms and interpretation

This document describes the [engine contract](docs/API_CONTRACT.md) and its interpretation. The parent verified 395 Python tests in 12.05 seconds, clean Ruff checks, successful npm build/check commands, 6 real-backend Chromium tests in 25.4 seconds and a successful synthetic benchmark. [DEVELOPMENT.md](DEVELOPMENT.md#known-integration-observations) records the measured fixture, stage timings, snapshot size and import-inclusive peak RSS. Independent bounded core and engines/frontend/container-configuration reviews reported no vulnerabilities; this is not certification. See [docs/VALIDATION.md](docs/VALIDATION.md) for consolidated evidence. Findings are review aids, not proof that a record is wrong.

On the toy fixture `[1, 2, 3, 4, 100]`, IQR and MAD each flagged row ID 4 with precision and recall 1.0. This verifies that fixture only, not general accuracy. The benchmark's 2,000-row synthetic CSV recognized all 20 expected missing values after the structural-blank fix. No host-independent performance or resource guarantee follows from one run.

## Input and identity

CSV inspection proposes encoding, delimiter and header choices; XLSX inspection lists sheets. Explicit choices are preferable when automatic inference is ambiguous. Expanded workbook size and expansion-ratio limits reduce decompression risk but do not guarantee hard memory isolation. Accepted rows and columns are capped before a dataset is published.

CSV ingestion distinguishes structural absence from literal strings: an **unquoted blank field becomes null**, while an explicitly quoted `""` remains an empty string. Literal `NA`, `null` and `?` tokens remain strings; they are not implicitly treated as missing. The CSV lexer retains quoting metadata, including escaped quotes and multiline fields. Numeric inference remains conservative: leading-zero identifiers stay strings rather than ordinary numbers. Normalize column labels to unique strings without adding internal row IDs to user data. Stable row IDs use the `__row_id__` index and survive transformations; selections refer to those IDs, not changing visual row positions. Mixed Excel scalar columns may need lossless string representations for Parquet, with documented warnings. No OCR, arbitrary PDF ingestion, macro execution, or database connection is part of this contract.

## Profiles and quality

Profiles include dimensions, missingness, duplicate rows, type distributions, empty/constant columns and column-specific summaries. Numeric summaries include central tendency, spread, quantiles, histogram, skewness, kurtosis, zeros, negatives and infinities when meaningful. Categorical/date summaries and a numeric correlation matrix complement them. Storage dtype and inferred semantic type are distinct: a string that resembles a date is not automatically converted.

Missing percentage is $100m/n$ for missing count $m$ among $n$ values; empty inputs require an explicit safe result rather than division by zero. Distinct counts and duplicates are diagnostics, not automatic instructions to delete. Constant and very small samples cannot support every statistic. JSON responses must not emit nonstandard NaN/Infinity literals; unavailable metrics need JSON-safe representations.

Profiles, issues and recommendations are cached by dataset/version and checked against an internal analysis revision. Older derived caches are refreshed lazily without changing snapshots or dataset metadata. Editing creates a new version; restoring can reuse a current cached earlier profile. Correlation indicates association, not causation. Samples and common values can be sensitive and remain on the authorized deterministic path, never in the AI payload.

Optional domain rules use `{column: {min: 0, max: 100}}`. The API exposes them through `POST /datasets/{id}/quality` with a strict `{"domain_rules": {...}}` body. Each column requires a finite numeric bound or `integer:true`; either bound may be omitted, and `min` must not exceed `max`. Optional `exclusive_min:true` requires `min` and rejects equality with it. For confirmed business rules, examples include quantity `{min:1,integer:true}`, positive prices `{min:0,exclusive_min:true}`, delivery days `{min:0,integer:true}`, ratings `{min:1,max:5}`, and discounts `{min:0,max:100}`. These checks operate on numeric columns; resolve mixed text through approved conversion first. Unknown columns or invalid rules return 422. This check is read-only, does not mutate versions, and does not change IQR/MAD thresholds or automatically infer business rules.

Quality issues carry category, severity, method, explanation, confidence, total count and a bounded row-ID list (contract maximum 200), plus a human-review flag. Recommendations include an operation, affected-record estimate, expected benefit, potential data loss, tradeoffs and `requires_approval:true`. Counts may exceed the number of examples shown. Domain plausibility and category resemblance are heuristics, not business-rule certification.

Spelling suggestions are limited to low-cardinality string columns (at most 100 distinct values and at most `max(2, floor(non_null_count * 0.2))`). Name/identifier/email/phone/address/date-like column names and values containing digits, email markers or recognized date shapes are excluded. Candidate labels must have similarity at least 85% but below 100%; the proposed canonical label must occur at least three times as often. Whitespace/case-only differences are separate formatting findings. At most 20 pairs are proposed, with exact original/canonical labels, affected-record counts, similarity, review confidence and an explicit mapping. Confidence is a heuristic, not a calibrated probability. This deliberately misses weak or uncertain typos; similarity never authorizes a merge and unnamed personal-name columns cannot be identified perfectly.

Date summaries separate valid, ambiguous, invalid and missing values. Supported shapes include ISO dates/timestamps, `YYYY/MM/DD`, and day/month or month/day forms using consistent slash or hyphen separators. Calendar-invalid dates remain invalid. Unequal day/month components both in 1..12 are ambiguous; equal components or a component above 12 can be resolved without guessing. Mixed valid formats are informational, not invalid-date findings. Unsupported text is invalid in a date-like column, not silently parsed with locale inference.

Text-column numeric readiness reports parseable/present counts and percentage, separate missing/invalid counts, and at most 200 invalid examples with stable row IDs and a truncation flag. Actual numeric statistics remain unavailable until conversion is approved. The parser rejects nonfinite values and precision-losing conversions. Resolve exact invalid tokens with `normalize_missing`, correct exact values with `map_categories`, then preview strict `to_numeric`; alternatively explicitly approve `coerce:true` to replace all invalid tokens with null. Identifier conversion is opt-in and can remove leading zeros.

The quality UI separates finding count, overlapping row occurrences and unique affected rows. When issue row-ID lists are truncated, the unique total is labeled as a lower bound. Empty anomaly/correlation views distinguish unavailable numeric data, no findings and undefined correlation; none proves a dataset is error-free.

## Anomaly methods

### Interquartile range (IQR)

For quartiles $Q_1,Q_3$, let $IQR=Q_3-Q_1$. With multiplier $k$ (default 1.5), flag values outside:

$$
[Q_1-k\,IQR,\ Q_3+k\,IQR]
$$

This is interpretable and insensitive to some extremes, but skewed/heavy-tailed valid data can be flagged. A zero-IQR column needs explicit degenerate-case handling, not unbounded arithmetic. Inspect reported thresholds and warnings.

### Median absolute deviation (MAD)

For median $\tilde{x}$:

$$
MAD=\operatorname{median}(|x_i-\tilde{x}|)
$$

The conventional modified score is $z_i=0.67448975(x_i-\tilde{x})/MAD$, commonly compared with an absolute threshold of 3.5. The contract selects a MAD method and default threshold; exact numerical conventions and zero-MAD behavior must be checked against implementation tests rather than assumed equivalent across libraries.

### Isolation Forest

A tree-based method isolates unusual observations using random partitions over selected numeric features. It can detect multivariate patterns not captured by a single-column fence. Feature selection, missing-value treatment, scale/distribution and fitted parameters affect results. The API ignores the supplied threshold for this method. No contamination estimate, random seed, runtime bound or detection-accuracy claim is made without implementation evidence. It does not automatically remove records.

## Explicit cleaning operations

All operations work on a deep copy; apply publishes a new immutable version only after preview and approval. An unchanged DataFrame, including dtypes, is a no-op: preview returns `no_changes:true`, approval is disabled, and direct apply returns HTTP 409 `no_changes` without creating history. Dtype-only conversions remain changes and are marked `schema_changed:true` even when no displayed cell values differ. Leading/trailing whitespace is made visible in preview cells; counts cover the full operation even when the table is sampled.

| Kind | Parameters / review concern |
| --- | --- |
| `trim` | Select a column; remove surrounding string whitespace, not arbitrary embedded content |
| `normalize_missing` | `tokens`: explicitly reviewed placeholders to turn into nulls; avoid erasing legitimate labels |
| `drop_duplicates` | `row_ids` required; remove selected duplicate records, not an automatic blanket deletion |
| `to_numeric` | `coerce` defaults false; coercion may lose nonnumeric information |
| `to_date` | Explicit strptime `format`, or `format:"supported"`; `coerce` defaults false; supported mode requires `date_order:"day_first"` or `"month_first"` for ambiguous values, even with coercion |
| `fill_missing` | `strategy`: median/mean/mode/constant; `value` for constant; may distort distributions |
| `drop_column` | Explicit column; all values in that column are removed from the new version |
| `case` | `mode`: lower/upper/title; may change case-sensitive identifiers |
| `map_categories` | Explicit `mapping`; similarity alone is not permission to merge categories |
| `handle_infinity` | Replace infinities with null; preserves the need for a later missing-data decision |
| `outliers` | Explicit `row_ids`, `action`: remove/clip; clipping uses `lower`/`upper` bounds |

Unknown parameters must fail explicitly. Row IDs identify source records; preview shows before/after changes and total affected counts. The server stores the reviewed operation and rejects a stale revision or expired preview. Undo/reset/restore change the active pointer rather than modifying prior snapshot contents.

Supported date conversion outputs UTC timestamps. Naive dates retain their calendar date; offset timestamps can change calendar date when normalized to UTC. Explicit-format parsing retains its existing timezone behavior. Unsupported or calendar-invalid values block conversion unless `coerce:true` is explicitly reviewed; ambiguous supported values never silently become null. Generated Python replays these parameters through the cleaning engine; reference SQL deliberately leaves date/numeric conversion untranslated.

For categorical frequencies and mode filling, only observed non-null values participate. Ties follow first observed occurrence, not the categorical dictionary order. Unused category labels are omitted from frequencies and cannot become an invented fill value for an all-null column. Counting does not change the stored categorical dtype.

## Exports and reproducibility

CSV exports use Python 3.12 `csv.QUOTE_NOTNULL`: null fields are unquoted blanks, while empty strings are quoted. This preserves the null-versus-empty distinction when reingested by DataLens; other CSV readers may apply different missing-value conventions.

CSV/XLSX exports must guard against spreadsheet formula execution in **both string cells and headers**. This can intentionally alter the exported textual representation; the internal original remains unchanged. HTML reports must escape untrusted text. The browser's native Print/Save as PDF flow displays the server-generated escaped HTML in a script-disabled sandboxed `srcdoc` frame, compatible with the existing CSP; it does not require a blob-frame allowance. There is no native server-side PDF-generation endpoint.

Generated Python and SQL are reference artifacts to review, not code run by the server. SQL uses the **PostgreSQL reference dialect**; unsupported transformations must be clearly commented, not represented as portable executable equivalents. Reference code follows the active branch's parent chain. It is not proof of byte-for-byte reproduction across environments, inferred types or database schemas.

## AI is not an algorithmic authority

Optional AI explains an aggregate-only summary; it receives no raw records or column names and cannot apply operations. Deterministic profiles, explicit thresholds and reviewed transformations remain the source of truth. Validate any provider explanation against those facts.
