"""Optional, aggregate-only explanations with a fail-closed free-model policy."""

import asyncio
import hashlib
import json
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.config import Settings

FREE_MODEL = 'openrouter/free'
MODELS_URL = 'https://openrouter.ai/api/v1/models'
COMPLETIONS_URL = 'https://openrouter.ai/api/v1/chat/completions'
CACHE_TTL_SECONDS = 3600
CACHE_MAX_ENTRIES = 128
CACHE_MAX_BYTES = 16384
CATALOGUE_MAX_BYTES = 4 * 1024 * 1024
RESPONSE_MAX_BYTES = 65536
BUSY_TIMEOUT_MS = 2000
MAX_COUNT = 10**12
SEMANTIC_TYPES = frozenset({
    'numeric', 'integer', 'decimal', 'boolean', 'datetime', 'date',
    'categorical', 'text', 'identifier', 'empty', 'mixed', 'unknown',
})
SYSTEM_PROMPT = (
    'Explain dataset quality using only the aggregate counts and anonymous semantic-type counts supplied. '
    'Do not invent column names, sample values, causes, or correlations. Do not recommend automatic changes. '
    'Return a JSON object with exactly explanation (a short plain-text string) and warnings '
    '(an array of short plain-text strings). Mention that any cleaning needs human review.'
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
 day TEXT PRIMARY KEY, attempts INTEGER NOT NULL CHECK(attempts >= 0)
);
CREATE TABLE IF NOT EXISTS ai_cache (
 cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, created_at REAL NOT NULL,
 expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_cache_expiry ON ai_cache(expires_at);
"""


class _Explanation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)

    explanation: Annotated[str, Field(min_length=1, max_length=4000)]
    warnings: Annotated[list[Annotated[str, Field(min_length=1, max_length=500)]], Field(max_length=8)]


class _Message(BaseModel):
    model_config = ConfigDict(strict=True)

    role: Literal['assistant']
    content: Annotated[str, Field(min_length=1, max_length=CACHE_MAX_BYTES)]
    refusal: None = None


class _Choice(BaseModel):
    model_config = ConfigDict(strict=True)

    message: _Message
    finish_reason: Literal['stop']


class _Completion(BaseModel):
    model_config = ConfigDict(strict=True)

    choices: Annotated[list[_Choice], Field(min_length=1, max_length=1)]
    error: None = None


class _Unavailable(Exception):
    def __init__(self, reason: str, retryable: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


def _count(value: object) -> int:
    return value if type(value) is int and 0 <= value <= MAX_COUNT else 0


def _summary(profile: dict) -> dict:
    # This allowlist is the privacy boundary: never serialize the original profile.
    summary = {key: _count(profile.get(key)) for key in (
        'rows', 'columns', 'total_cells', 'missing_cells', 'duplicate_rows',
    )}
    for key in ('empty_columns', 'constant_columns'):
        value = profile.get(key)
        summary[key] = len(value) if isinstance(value, list) else _count(value)
    distribution = profile.get('type_distribution')
    types: dict[str, int] = {}
    if isinstance(distribution, dict):
        for name, value in distribution.items():
            safe_name = name if isinstance(name, str) and name in SEMANTIC_TYPES else 'unknown'
            types[safe_name] = min(MAX_COUNT, types.get(safe_name, 0) + _count(value))
    summary['semantic_type_counts'] = {name: count for name, count in sorted(types.items()) if count}
    return summary


def _fallback(summary: dict, reason: str) -> dict:
    return {
        'source': 'deterministic',
        'explanation': (
            f"The dataset contains {summary['rows']} rows and {summary['columns']} columns. "
            f"There are {summary['missing_cells']} missing cells out of {summary['total_cells']} cells, "
            f"{summary['duplicate_rows']} duplicate rows, {summary['empty_columns']} empty columns, "
            f"and {summary['constant_columns']} constant columns. "
            'Review missing values, duplicates, and constant columns before deciding on cleaning. '
            'These counts alone do not establish causes or justify deleting data. '
            'No data has been changed; all cleaning requires human review.'
        ),
        'warnings': ['AI is unavailable; deterministic profiling and cleaning remain available.'],
        'reason': reason,
    }


def _verify_free_catalogue(data: object) -> None:
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise _Unavailable('cost_unverified')
    matches = [entry for entry in data['data'] if isinstance(entry, dict) and entry.get('id') == FREE_MODEL]
    if len(matches) != 1:
        raise _Unavailable('cost_unverified')
    pricing = matches[0].get('pricing')
    if not isinstance(pricing, dict) or not {'prompt', 'completion'} <= pricing.keys():
        raise _Unavailable('cost_unverified')
    # Check every listed charge, including new pricing fields, not just token prices.
    for price in pricing.values():
        if type(price) not in (str, int, float, Decimal) or len(str(price)) > 100:
            raise _Unavailable('cost_unverified')
        try:
            amount = Decimal(str(price))
        except InvalidOperation:
            raise _Unavailable('cost_unverified') from None
        if not amount.is_finite() or amount != 0:
            raise _Unavailable('cost_unverified')


class AIGateway:
    def __init__(self, settings: Settings, db_path: Path):
        self.settings = settings
        self.db_path = Path(db_path)
        self._storage_ready = False
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self._connect() as db:
                db.executescript(SCHEMA)
                self._prune_cache(db, time.time())
            self._storage_ready = True
        except (OSError, sqlite3.Error):
            # Provider/storage exceptions must not escape into application logs.
            pass

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            db.execute(f'PRAGMA busy_timeout={BUSY_TIMEOUT_MS}')
            with db:
                yield db
        finally:
            db.close()

    def _policy_reason(self) -> str | None:
        if not self.settings.ai_enabled:
            return 'disabled'
        # ai_zero_cost_mode=False deliberately cannot relax this policy.
        if self.settings.openrouter_model != FREE_MODEL:
            return 'model_not_allowed'
        if not self.settings.openrouter_api_key.get_secret_value().strip():
            return 'missing_key'
        if not self._storage_ready:
            return 'storage_unavailable'
        return None

    @property
    def _daily_limit(self) -> int:
        return min(45, max(0, self.settings.ai_daily_request_limit))

    def status(self) -> dict:
        """Report local eligibility, without an HTTP request or live-price claim."""
        reason = self._policy_reason()
        if reason is None:
            try:
                with self._connect() as db:
                    row = db.execute('SELECT attempts FROM ai_usage WHERE day=?', (self._day(),)).fetchone()
                if (row[0] if row else 0) >= self._daily_limit:
                    reason = 'quota_exhausted'
            except sqlite3.Error:
                reason = 'storage_unavailable'
        return {
            'enabled': self.settings.ai_enabled,
            'available': reason is None,
            'model': self.settings.openrouter_model,
            'reason': reason,
        }

    @staticmethod
    def _day() -> str:
        return datetime.now(UTC).date().isoformat()

    def _reserve_attempt(self) -> None:
        with self._connect() as db:
            # Reserve and commit before network I/O; never refund uncertain attempts.
            db.execute('BEGIN IMMEDIATE')
            day = self._day()
            row = db.execute('SELECT attempts FROM ai_usage WHERE day=?', (day,)).fetchone()
            if (row[0] if row else 0) >= self._daily_limit:
                raise _Unavailable('quota_exhausted')
            db.execute(
                'INSERT INTO ai_usage(day,attempts) VALUES (?,1) '
                'ON CONFLICT(day) DO UPDATE SET attempts=attempts+1', (day,),
            )
            oldest = (datetime.fromisoformat(day) - timedelta(days=31)).date().isoformat()
            db.execute('DELETE FROM ai_usage WHERE day < ?', (oldest,))

    @staticmethod
    def _prune_cache(db: sqlite3.Connection, now: float) -> None:
        db.execute('DELETE FROM ai_cache WHERE expires_at <= ? OR created_at > ?', (now, now))
        db.execute(
            'DELETE FROM ai_cache WHERE cache_key IN '
            '(SELECT cache_key FROM ai_cache ORDER BY created_at DESC,cache_key LIMIT -1 OFFSET ?)',
            (CACHE_MAX_ENTRIES,),
        )

    def _cache_get(self, key: str) -> _Explanation | None:
        with self._connect() as db:
            self._prune_cache(db, time.time())
            row = db.execute('SELECT response FROM ai_cache WHERE cache_key=?', (key,)).fetchone()
            if row is None:
                return None
            try:
                if not isinstance(row[0], str) or len(row[0].encode('utf-8')) > CACHE_MAX_BYTES:
                    raise ValueError
                return _Explanation.model_validate_json(row[0])
            except (ValueError, ValidationError):
                db.execute('DELETE FROM ai_cache WHERE cache_key=?', (key,))
                return None

    def _cache_put(self, key: str, result: _Explanation) -> None:
        encoded = result.model_dump_json()
        if len(encoded.encode('utf-8')) > CACHE_MAX_BYTES:
            return
        now = time.time()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute(
                'INSERT OR REPLACE INTO ai_cache(cache_key,response,created_at,expires_at) VALUES (?,?,?,?)',
                (key, encoded, now, now + CACHE_TTL_SECONDS),
            )
            self._prune_cache(db, now)

    async def _request(self, client: httpx.AsyncClient, method: str, url: str, **kwargs) -> object:
        await asyncio.to_thread(self._reserve_attempt)
        cap = CATALOGUE_MAX_BYTES if method == 'GET' else RESPONSE_MAX_BYTES
        try:
            async with asyncio.timeout(min(30, self.settings.ai_request_timeout_seconds)):
                async with client.stream(method, url, **kwargs) as response:
                    if response.status_code != 200:
                        raise _Unavailable(
                            'provider_error', response.status_code in {408, 429, 500, 502, 503, 504},
                        )
                    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                        raise _Unavailable('invalid_response')
                    length = response.headers.get('content-length')
                    if length is not None and int(length) > cap:
                        raise _Unavailable('response_too_large')
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        if len(body) + len(chunk) > cap:
                            raise _Unavailable('response_too_large')
                        body.extend(chunk)
            # Preserve tiny nonzero catalogue prices instead of rounding them to float zero.
            return json.loads(body, parse_float=Decimal, parse_constant=Decimal)
        except (httpx.TimeoutException, TimeoutError):
            raise _Unavailable('timeout', retryable=True) from None
        except httpx.TransportError:
            raise _Unavailable('provider_error', retryable=True) from None
        except (ValueError, InvalidOperation, UnicodeError, RecursionError, httpx.HTTPError):
            raise _Unavailable('invalid_response') from None

    async def explain(self, profile: dict) -> dict:
        summary = _summary(profile)
        reason = self._policy_reason()
        if reason is not None:
            return _fallback(summary, reason)
        context = json.dumps(summary, sort_keys=True, separators=(',', ':'))
        key = hashlib.sha256((FREE_MODEL + SYSTEM_PROMPT + context).encode('utf-8')).hexdigest()
        try:
            if self.settings.ai_cache_enabled:
                cached = await asyncio.to_thread(self._cache_get, key)
                if cached is not None:
                    return {'source': 'cache', **cached.model_dump(), 'reason': None}
            payload = {
                'model': FREE_MODEL,
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': context},
                ],
                'provider': {
                    'allow_fallbacks': False,
                    'require_parameters': True,
                    'data_collection': 'deny',
                    'max_price': {'prompt': 0, 'completion': 0, 'request': 0, 'image': 0, 'audio': 0},
                },
                'response_format': {'type': 'json_object'},
                'max_tokens': 700,
                'temperature': 0,
                'stream': False,
            }
            async with httpx.AsyncClient(
                timeout=min(30, self.settings.ai_request_timeout_seconds),
                follow_redirects=False, trust_env=False,
                headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'},
            ) as client:
                for attempt in range(min(1, max(0, self.settings.ai_max_retries)) + 1):
                    try:
                        catalogue = await self._request(client, 'GET', MODELS_URL)
                        _verify_free_catalogue(catalogue)
                        data = await self._request(
                            client, 'POST', COMPLETIONS_URL,
                            headers={'Authorization': f'Bearer {self.settings.openrouter_api_key.get_secret_value()}'},
                            json=payload,
                        )
                        completion = _Completion.model_validate(data)
                        result = _Explanation.model_validate_json(completion.choices[0].message.content)
                        if self.settings.ai_cache_enabled:
                            await asyncio.to_thread(self._cache_put, key, result)
                        return {'source': 'ai', **result.model_dump(), 'reason': None}
                    except _Unavailable as exc:
                        if not exc.retryable or attempt >= min(1, max(0, self.settings.ai_max_retries)):
                            return _fallback(summary, exc.reason)
                        await asyncio.sleep(0.1)
        except _Unavailable as exc:
            return _fallback(summary, exc.reason)
        except (sqlite3.Error, OSError):
            return _fallback(summary, 'storage_unavailable')
        except (ValueError, ValidationError, TypeError, RecursionError, httpx.HTTPError):
            return _fallback(summary, 'invalid_response')
        return _fallback(summary, 'provider_error')
