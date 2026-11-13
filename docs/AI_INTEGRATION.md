# Optional AI explanations

## Integration

```python
from backend.ai import AIGateway

# Reuse the application's already-constructed Settings and SQLite path.
gateway = AIGateway(settings, db_path)
status = gateway.status()
result = await gateway.explain(profile)
```

`status()` returns `{enabled, available, model, reason}` without network activity.
`available` means local configuration, storage and quota permit an attempt; it is
not a claim that live pricing or provider availability has already been verified.
`explain()` returns `{source, explanation, warnings, reason}`. Sources are `ai`,
`cache`, or `deterministic`. Successful AI/cache results have `reason: null`.
Failures return a deterministic count-based explanation, never a provider error
body. Existing profiling, cleaning and export functionality remains independent.

Use one gateway per application. Separate gateway instances/processes may share
the database safely: each operation opens its own SQLite connection with a
2-second busy timeout. Only `ai_usage`, `ai_cache`, and the cache-expiry index are
created. No application dataset tables are read or modified.

## Privacy and credentials

The gateway does not construct settings or read `.env`. Pass settings from the
application; unit tests explicitly disable dotenv loading and use only a fake key.
The only external dataset context is a fixed allowlist of aggregate counts:
rows, columns, total/missing cells, duplicate rows, empty/constant column counts,
and anonymous semantic-type counts. Empty/constant column lists become counts.
Only fixed semantic-type labels are allowed; other labels become `unknown`.
Numeric strings, booleans, negative, nonfinite and excessively large counts are
excluded. Column profiles, names, samples, category values, numerical statistics,
correlation matrices, filenames, instructions and other raw values are never sent.
The public catalogue request has no authorization header. Only the fixed
completion endpoint receives the key. Environment proxies and redirects are
disabled. This module never logs prompts, credentials or arbitrary provider errors.
Aggregate counts still describe the dataset and are not differential privacy.
Provider text is advisory and untrusted: render it as text, never executable HTML,
SQL, Python, or an automatically approved cleaning operation.

## Fail-closed cost policy

Only the exact model `openrouter/free` is accepted, even when
`ai_zero_cost_mode=False`. No `models` fallback list, plugins, tools, paid model,
`:free` model selected directly, or configurable endpoint is permitted.
Immediately before every completion attempt, a bounded `GET` to
`https://openrouter.ai/api/v1/models` must contain exactly one matching router
entry. Its `pricing.prompt` and `pricing.completion` must be explicitly zero.
Every other listed pricing field must also be a finite numeric zero; unknown,
missing required, null, negative or nonzero pricing fails closed.

Requests use `POST https://openrouter.ai/api/v1/chat/completions` with
`provider.max_price` prompt/completion/request/image/audio all set to zero,
`allow_fallbacks: false`, `require_parameters: true`, and
`data_collection: deny`. These restrictions may make a free model unavailable;
they are never removed to obtain an answer. The response requests JSON, at most
700 output tokens, no streaming, and is validated locally with Pydantic. Only a
complete assistant response containing the bounded explanation/warnings object
is accepted; truncated, refused, malformed or oversized responses fall back.

## Resource limits

- The persistent UTC daily quota counts **every attempted HTTP request**, including
  catalogue GETs, unsuccessful POSTs and retries. Reservations commit atomically
  before sending, with no refunds on failure or cancellation. It is capped at 45
  attempts/day (usually at most 22 uncached successful explanations). Zero disables
  outgoing requests. Catalogue verification may consume the last attempt without
  leaving quota for a completion. Old usage rows are pruned after 31 days.
- `ai_max_retries` permits at most one retry for the whole explanation sequence.
  Only transport failures, timeouts and selected transient HTTP statuses retry.
  A retried completion requires another price verification. At most four HTTP
  attempts occur. Backoff is 0.1 seconds; `Retry-After` cannot extend it.
- Each HTTP attempt has both HTTPX timeouts and a whole-attempt deadline, at most
  30 seconds. The deadline does not include the preceding SQLite reservation.
  HTTP catalogue bodies are capped at 4 MiB; completion bodies at 64 KiB.
  Reading stops at the cap, including without Content-Length. Compressed responses
  are rejected, preventing decompression from bypassing the cap.
- Validated explanations are cached for a fixed one-hour TTL, at most 128 entries
  and 16 KiB per value. Keys hash only the sanitized context and prompt/model
  version. Cache values are revalidated on reads; corrupt values are deleted.
  Cache hits spend no quota and remain usable after quota exhaustion. Disabling
  AI or rejecting the model always takes precedence over a cache hit. Disabling
  caching bypasses existing cache entries. Cache expiry is cleaned on operations
  and initialization, rather than by a background service.
- Storage failures fail closed for network use. Deleting the database resets
  quota accounting; the database must remain durable across application restarts.
  System clock correctness is required for UTC quotas and TTL.

## Official sources and limitations

Verified against official documentation on 2026-11-13; no authenticated catalogue
or completion request was made during implementation.

- [Free Models Router](https://openrouter.ai/docs/guides/routing/routers/free-router):
  explicitly describes `openrouter/free` as completely free, including the router
  and routed requests. Model selection and availability vary.
- [Free model variants](https://openrouter.ai/docs/guides/routing/model-variants/free):
  explicitly warns that paid entries in fallback lists are billed; recommends the
  free router alone to remain on free models.
- [Chat Completions API](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion):
  documents the production base URL and `POST /chat/completions`, messages, model,
  output-token bounds and provider preference fields.
- [Provider routing / max price](https://openrouter.ai/docs/guides/routing/provider-selection#max-price):
  documents `provider.max_price` as a highest accepted price, including prompt,
  completion, request and image limits. The Chat Completions schema additionally
  lists audio. Prompt/completion limits use USD per million tokens. Zero has the
  same meaning regardless of token-unit conversion. The routing guide uses numeric
  limits; the current API schema describes string-encoded prices. This integration
  sends numeric zeros as in the guide. If rejected, it falls back rather than
  retrying without constraints.
- [Models catalogue](https://openrouter.ai/docs/guides/overview/models): documents
  the public models endpoint and model pricing metadata.

The documentation establishes generic Chat Completions/provider parameter support,
not a guarantee that every currently selected free model supports all restrictions.
Provider-side enforcement and live router availability were not integration-tested
with a real credential. Catalogue metadata can change between verification and
completion; the fixed free router and zero-price constraints are independent
additional protections, not an audit of an account's billing configuration.
Free-provider limits, outages, schema changes and oversized catalogues intentionally
reduce AI availability rather than relax safety constraints. Cache validity does
not revalidate live pricing because a cache hit makes no external request.

## Verification

```bash
.venv/bin/python -m pytest tests/test_ai.py -q -p no:cacheprovider
.venv/bin/python -m ruff check backend/ai.py tests/test_ai.py
```

All tests inject HTTPX MockTransport; none contact a provider. Tests keep isolated
SQLite files under `.ai-test-state/` in the project and clean them afterward.
