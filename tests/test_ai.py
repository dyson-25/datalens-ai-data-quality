import asyncio
import json
import logging
import shutil
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from backend import ai
from backend.ai import AIGateway
from backend.config import Settings

TEST_KEY = 'synthetic-unit-test-key-not-a-real-credential'
PROFILE = {
    'rows': 20, 'columns': 3, 'total_cells': 60, 'missing_cells': 4,
    'duplicate_rows': 2, 'empty_columns': [], 'constant_columns': ['private-column'],
    'type_distribution': {'numeric': 1, 'categorical': 1, 'text': 1},
}


def settings(**overrides):
    # Explicit input takes precedence over environment variables; never load .env.
    values = {
        'app_env': 'test', 'ai_enabled': True, 'ai_zero_cost_mode': True,
        'openrouter_api_key': TEST_KEY, 'openrouter_model': ai.FREE_MODEL,
        'ai_request_timeout_seconds': 1, 'ai_max_retries': 1,
        'ai_cache_enabled': True, 'ai_daily_request_limit': 45,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def catalogue(pricing=None):
    return {'data': [{'id': ai.FREE_MODEL, 'pricing': pricing if pricing is not None else {
        'prompt': '0', 'completion': '0', 'request': '0', 'image': '0',
        'web_search': '0', 'internal_reasoning': '0', 'input_cache_read': '0',
    }}]}


def completion(content=None, **overrides):
    result = {'choices': [{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': content if content is not None else json.dumps({
            'explanation': 'Review missing cells and duplicates before making changes.',
            'warnings': ['Cleaning requires human review.'],
        }),
    }}]}
    result.update(overrides)
    return result


class Provider:
    def __init__(self):
        self.requests = []
        self.catalogue = catalogue()
        self.completion = completion()
        self.get_responses = []
        self.post_responses = []

    def handle(self, request):
        self.requests.append(request)
        assert str(request.url) in {ai.MODELS_URL, ai.COMPLETIONS_URL}
        assert request.headers['accept-encoding'] == 'identity'
        responses = self.get_responses if request.method == 'GET' else self.post_responses
        if responses:
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        data = self.catalogue if request.method == 'GET' else self.completion
        return httpx.Response(200, content=json.dumps(data), headers={'content-type': 'application/json'})


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    fake = Provider()
    original_client = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs['trust_env'] is False
        assert kwargs['follow_redirects'] is False
        return original_client(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(ai.httpx, 'AsyncClient', factory)
    return fake


@pytest.fixture
def db_path():
    root = Path(__file__).resolve().parents[1] / '.ai-test-state'
    directory = root / uuid4().hex
    directory.mkdir(parents=True)
    try:
        yield directory / 'shared.sqlite3'
    finally:
        shutil.rmtree(directory)
        try:
            root.rmdir()
        except OSError:
            pass


def explain(gateway, profile=None):
    return asyncio.run(gateway.explain(PROFILE if profile is None else profile))


def attempts(db_path):
    with sqlite3.connect(db_path) as db:
        return db.execute('SELECT COALESCE(SUM(attempts),0) FROM ai_usage').fetchone()[0]


@pytest.mark.parametrize(('options', 'reason'), [
    ({'ai_enabled': False}, 'disabled'),
    ({'openrouter_api_key': ''}, 'missing_key'),
    ({'openrouter_api_key': '   '}, 'missing_key'),
    ({'openrouter_model': 'paid/model'}, 'model_not_allowed'),
    ({'ai_zero_cost_mode': False, 'openrouter_model': 'paid/model'}, 'model_not_allowed'),
    ({'openrouter_model': 'vendor/model:free'}, 'model_not_allowed'),
    ({'openrouter_model': 'openrouter/free '}, 'model_not_allowed'),
])
def test_disabled_missing_key_and_model_policy(db_path, provider, options, reason):
    gateway = AIGateway(settings(**options), db_path)
    assert gateway.status() == {
        'enabled': options.get('ai_enabled', True), 'available': False,
        'model': options.get('openrouter_model', ai.FREE_MODEL), 'reason': reason,
    }
    result = explain(gateway)
    assert result['source'] == 'deterministic'
    assert result['reason'] == reason
    assert '20 rows and 3 columns' in result['explanation']
    assert 'private-column' not in json.dumps(result)
    assert result == explain(gateway)
    assert set(result) == {'source', 'explanation', 'warnings', 'reason'}
    assert provider.requests == []
    assert attempts(db_path) == 0


def test_status_is_local_and_does_not_claim_live_provider_verification(db_path, provider):
    gateway = AIGateway(settings(), db_path)
    assert gateway.status() == {
        'enabled': True, 'available': True, 'model': ai.FREE_MODEL, 'reason': None,
    }
    assert provider.requests == []


@pytest.mark.parametrize('pricing', [
    {}, {'prompt': '0'}, {'completion': '0'},
    {'prompt': '0.001', 'completion': '0'},
    {'prompt': '0', 'completion': '0.001'},
    {'prompt': '0', 'completion': '0', 'request': '0.01'},
    {'prompt': '0', 'completion': '0', 'image': '0.01'},
    {'prompt': '0', 'completion': '0', 'web_search': '1'},
    {'prompt': '0', 'completion': '0', 'input_cache_read': '1'},
    {'prompt': '0', 'completion': '0', 'future_charge': '1'},
    {'prompt': '0', 'completion': '0', 'future_charge': None},
    {'prompt': 'NaN', 'completion': '0'},
    {'prompt': 'Infinity', 'completion': '0'},
    {'prompt': '-1', 'completion': '0'},
    {'prompt': True, 'completion': '0'},
    {'prompt': [], 'completion': '0'},
    {'prompt': 'not-a-price', 'completion': '0'},
    {'prompt': '1e-9999', 'completion': '0'},
])
@pytest.mark.parametrize('zero_cost_mode', [True, False])
def test_nonzero_unknown_or_missing_price_fails_closed(db_path, provider, pricing, zero_cost_mode):
    provider.catalogue = catalogue(pricing)
    result = explain(AIGateway(settings(ai_zero_cost_mode=zero_cost_mode), db_path))
    assert result['reason'] == 'cost_unverified'
    assert result['source'] == 'deterministic'
    assert [request.method for request in provider.requests] == ['GET']
    assert attempts(db_path) == 1


@pytest.mark.parametrize('data', [
    None, [], {}, {'data': None}, {'data': []}, {'data': ['invalid']},
    {'data': [{'id': 'paid/model', 'pricing': {'prompt': '0', 'completion': '0'}}]},
    {'data': [{'id': ai.FREE_MODEL, 'pricing': None}]},
    {'data': catalogue()['data'] * 2},
])
def test_missing_ambiguous_or_malformed_catalogue_rejects_completion(db_path, provider, data):
    provider.catalogue = data
    assert explain(AIGateway(settings(), db_path))['reason'] == 'cost_unverified'
    assert len(provider.requests) == 1


def test_raw_numeric_price_cannot_underflow_to_zero(db_path, provider):
    provider.get_responses = [httpx.Response(200, content=(
        b'{"data":[{"id":"openrouter/free","pricing":{"prompt":1e-9999,"completion":0}}]}'
    ))]
    assert explain(AIGateway(settings(), db_path))['reason'] == 'cost_unverified'
    assert [request.method for request in provider.requests] == ['GET']


def test_exact_zero_prices_and_request_cost_constraints(db_path, provider):
    provider.catalogue = catalogue({'prompt': 0, 'completion': '0.000', 'future_charge': '-0'})
    gateway = AIGateway(settings(ai_zero_cost_mode=False), db_path)
    result = explain(gateway)
    assert result['source'] == 'ai'
    assert result['reason'] is None
    assert [request.method for request in provider.requests] == ['GET', 'POST']
    get, post = provider.requests
    assert 'authorization' not in get.headers
    assert post.headers['authorization'] == f'Bearer {TEST_KEY}'
    payload = json.loads(post.content)
    assert payload['model'] == ai.FREE_MODEL
    assert 'models' not in payload
    assert 'plugins' not in payload
    assert 'tools' not in payload
    assert payload['provider'] == {
        'allow_fallbacks': False, 'require_parameters': True, 'data_collection': 'deny',
        'max_price': {'prompt': 0, 'completion': 0, 'request': 0, 'image': 0, 'audio': 0},
    }
    assert payload['max_tokens'] == 700
    assert payload['response_format'] == {'type': 'json_object'}
    assert payload['stream'] is False
    assert attempts(db_path) == 2


@pytest.mark.parametrize(('limit', 'methods'), [(0, []), (1, ['GET']), (2, ['GET', 'POST'])])
def test_persistent_quota_counts_each_http_attempt(db_path, provider, limit, methods):
    config = settings(ai_daily_request_limit=limit, ai_cache_enabled=False)
    gateway = AIGateway(config, db_path)
    first = explain(gateway)
    assert first['source'] == ('ai' if limit == 2 else 'deterministic')
    restarted = AIGateway(config, db_path)
    assert explain(restarted)['reason'] == 'quota_exhausted'
    assert restarted.status()['reason'] == 'quota_exhausted'
    assert attempts(db_path) == limit
    assert [request.method for request in provider.requests] == methods


def test_quota_reservation_is_atomic_between_instances(db_path):
    config = settings(ai_daily_request_limit=3)
    gateways = [AIGateway(config, db_path) for _ in range(8)]
    barrier = threading.Barrier(len(gateways))

    def reserve(gateway):
        barrier.wait()
        try:
            gateway._reserve_attempt()
            return True
        except ai._Unavailable as exc:
            assert exc.reason == 'quota_exhausted'
            return False

    with ThreadPoolExecutor(max_workers=len(gateways)) as executor:
        assert sum(executor.map(reserve, gateways)) == 3
    assert attempts(db_path) == 3


def test_daily_quota_resets_utc_and_usage_history_is_bounded(db_path, provider, monkeypatch):
    gateway = AIGateway(settings(ai_daily_request_limit=2, ai_cache_enabled=False), db_path)
    monkeypatch.setattr(gateway, '_day', lambda: '2026-01-01')
    assert explain(gateway)['source'] == 'ai'
    assert explain(gateway)['reason'] == 'quota_exhausted'
    monkeypatch.setattr(gateway, '_day', lambda: '2026-02-15')
    assert explain(gateway)['source'] == 'ai'
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT day,attempts FROM ai_usage').fetchall() == [('2026-02-15', 2)]


@pytest.mark.parametrize('failure', [
    httpx.Response(429, text='private arbitrary provider error'),
    httpx.Response(500, text='private arbitrary provider error'),
    httpx.ConnectError('private arbitrary provider error'),
    httpx.ReadTimeout('private arbitrary provider error'),
])
def test_retry_counts_failures_and_reverifies_catalogue(db_path, provider, failure, caplog):
    caplog.set_level(logging.DEBUG)
    provider.post_responses = [failure]
    result = explain(AIGateway(settings(), db_path))
    assert result['source'] == 'ai'
    assert [r.method for r in provider.requests] == ['GET', 'POST', 'GET', 'POST']
    assert attempts(db_path) == 4
    assert 'private arbitrary provider error' not in caplog.text
    assert TEST_KEY not in caplog.text


def test_retry_stops_at_local_quota(db_path, provider):
    provider.post_responses = [httpx.Response(429)]
    result = explain(AIGateway(settings(ai_daily_request_limit=2), db_path))
    assert result['reason'] == 'quota_exhausted'
    assert attempts(db_path) == 2
    assert [r.method for r in provider.requests] == ['GET', 'POST']


def test_catalogue_retry_uses_same_small_retry_budget(db_path, provider):
    provider.get_responses = [httpx.Response(503)]
    provider.post_responses = [httpx.Response(503)]
    assert explain(AIGateway(settings(), db_path))['reason'] == 'provider_error'
    assert [r.method for r in provider.requests] == ['GET', 'GET', 'POST']
    assert attempts(db_path) == 3


def test_retry_rechecks_prices_and_stops_if_changed(db_path, provider):
    provider.get_responses = [httpx.Response(200, json=catalogue())]
    provider.catalogue = catalogue({'prompt': '1', 'completion': '0'})
    provider.post_responses = [httpx.Response(503)]
    assert explain(AIGateway(settings(), db_path))['reason'] == 'cost_unverified'
    assert [r.method for r in provider.requests] == ['GET', 'POST', 'GET']


@pytest.mark.parametrize('retries', [0, 1])
def test_limited_retries_and_no_response_errors_exposed(db_path, provider, retries, caplog):
    caplog.set_level(logging.DEBUG)
    private = 'PRIVATE_PROVIDER_ERROR_AND_PROMPT'
    provider.post_responses = [httpx.Response(503, text=private), httpx.Response(503, text=private)]
    result = explain(AIGateway(settings(ai_max_retries=retries), db_path))
    assert result['reason'] == 'provider_error'
    assert attempts(db_path) == 2 * (1 + retries)
    assert private not in json.dumps(result)
    assert private not in caplog.text
    assert TEST_KEY not in caplog.text


@pytest.mark.parametrize('status', [301, 302, 307, 308, 400, 401, 402, 403, 404, 422])
def test_redirects_and_nontransient_errors_never_retry(db_path, provider, status):
    provider.post_responses = [httpx.Response(status, headers={'location': 'https://untrusted.invalid'})]
    assert explain(AIGateway(settings(), db_path))['reason'] == 'provider_error'
    assert attempts(db_path) == 2
    assert len(provider.requests) == 2


@pytest.mark.parametrize('data', [
    None, [], {}, {'error': {'message': 'private'}}, {'choices': []},
    {'choices': [{'message': {'content': '{}'}}]},
    {'choices': [{'finish_reason': 'length', 'message': {'role': 'assistant', 'content': '{}'}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': None}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'role': 'user', 'content': '{}'}}]},
    {'choices': completion()['choices'] * 2},
    completion(error={'message': 'private'}),
    completion(content='not JSON'),
    completion(content='```json\n{"explanation":"hello","warnings":[]}\n```'),
    completion(content='{}'),
    completion(content='{"explanation":"hello"}'),
    completion(content='{"explanation":1,"warnings":[]}'),
    completion(content='{"explanation":"","warnings":[]}'),
    completion(content='{"explanation":"   ","warnings":[]}'),
    completion(content='{"explanation":"hello","warnings":"warning"}'),
    completion(content='{"explanation":"hello","warnings":[1]}'),
    completion(content='{"explanation":"hello","warnings":[],"instructions":"private"}'),
    completion(content=json.dumps({'explanation': 'a' * 4001, 'warnings': []})),
    completion(content=json.dumps({'explanation': 'hello', 'warnings': ['a'] * 9})),
    completion(content=json.dumps({'explanation': 'hello', 'warnings': ['a' * 501]})),
])
def test_malformed_provider_output_falls_back_without_cache_or_retry(db_path, provider, data):
    provider.completion = data
    result = explain(AIGateway(settings(), db_path))
    assert result['reason'] == 'invalid_response'
    assert 'private' not in json.dumps(result)
    assert len(provider.requests) == 2
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM ai_cache').fetchone()[0] == 0


class Chunks(httpx.AsyncByteStream):
    def __init__(self, size, count):
        self.size = size
        self.count = count
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for _ in range(self.count):
            self.read += 1
            yield b'x' * self.size

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize('endpoint', ['get', 'post'])
def test_stream_response_byte_cap_stops_reading_and_closes(db_path, provider, monkeypatch, endpoint):
    monkeypatch.setattr(ai, 'CATALOGUE_MAX_BYTES', 16384)
    monkeypatch.setattr(ai, 'RESPONSE_MAX_BYTES', 16384)
    stream = Chunks(8192, 100)
    getattr(provider, f'{endpoint}_responses').append(httpx.Response(200, stream=stream))
    result = explain(AIGateway(settings(), db_path))
    assert result['reason'] == 'response_too_large'
    assert stream.read == 3
    assert stream.closed
    assert len(provider.requests) == (1 if endpoint == 'get' else 2)


@pytest.mark.parametrize(('headers', 'reason'), [
    ({'content-length': str(ai.RESPONSE_MAX_BYTES + 1)}, 'response_too_large'),
    ({'content-length': 'invalid'}, 'invalid_response'),
    ({'content-encoding': 'gzip'}, 'invalid_response'),
])
def test_bad_or_oversized_headers_rejected_before_reading(db_path, provider, headers, reason):
    stream = Chunks(1, 100)
    provider.post_responses = [httpx.Response(200, headers=headers, stream=stream)]
    assert explain(AIGateway(settings(), db_path))['reason'] == reason
    assert stream.read == 0
    assert stream.closed


@pytest.mark.parametrize('body', [b'\xff', b'{invalid', b'[]', b'[' * 2000])
def test_invalid_raw_response_json_is_safe(db_path, provider, body):
    provider.post_responses = [httpx.Response(200, content=body)]
    assert explain(AIGateway(settings(), db_path))['reason'] == 'invalid_response'
    assert len(provider.requests) == 2


def test_total_attempt_timeout_closes_slow_response(db_path, provider):
    class Slow(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            await asyncio.sleep(5)
            yield b'{}'

        async def aclose(self):
            self.closed = True

    stream = Slow()
    provider.post_responses = [httpx.Response(200, stream=stream)]
    started = time.monotonic()
    assert explain(AIGateway(settings(ai_max_retries=0), db_path))['reason'] == 'timeout'
    assert time.monotonic() - started < 3
    assert stream.closed
    assert attempts(db_path) == 2


def test_cache_survives_restart_is_validated_and_works_at_quota(db_path, provider):
    config = settings(ai_daily_request_limit=2)
    first = explain(AIGateway(config, db_path))
    restarted = AIGateway(config, db_path)
    second = explain(restarted)
    assert second == {**first, 'source': 'cache'}
    assert restarted.status()['reason'] == 'quota_exhausted'
    assert len(provider.requests) == 2
    assert attempts(db_path) == 2
    with sqlite3.connect(db_path) as db:
        key, response = db.execute('SELECT cache_key,response FROM ai_cache').fetchone()
        assert len(key) == 64
        assert json.loads(response) == {'explanation': first['explanation'], 'warnings': first['warnings']}
        assert TEST_KEY not in response
        assert 'private-column' not in response


@pytest.mark.parametrize('broken', ['not-json', '{}', '{"explanation":1,"warnings":[]}', 'x' * 20000])
def test_corrupt_cache_is_evicted_and_never_returned(db_path, provider, broken):
    gateway = AIGateway(settings(), db_path)
    assert explain(gateway)['source'] == 'ai'
    with sqlite3.connect(db_path) as db:
        db.execute('UPDATE ai_cache SET response=?', (broken,))
    assert explain(gateway)['source'] == 'ai'
    assert len(provider.requests) == 4


def test_cache_ttl_is_fixed_not_sliding(db_path, provider, monkeypatch):
    gateway = AIGateway(settings(), db_path)
    clock = time.time()
    monkeypatch.setattr(ai.time, 'time', lambda: clock)
    assert explain(gateway)['source'] == 'ai'
    clock += ai.CACHE_TTL_SECONDS - 1
    assert explain(gateway)['source'] == 'cache'
    clock += 1
    assert explain(gateway)['source'] == 'ai'
    assert len(provider.requests) == 4


def test_cache_size_is_bounded_with_independent_connections(db_path, provider, monkeypatch):
    monkeypatch.setattr(ai, 'CACHE_MAX_ENTRIES', 2)
    gateway = AIGateway(settings(), db_path)
    with gateway._connect() as db:
        assert db.execute('PRAGMA busy_timeout').fetchone()[0] == ai.BUSY_TIMEOUT_MS
    clock = time.time()
    monkeypatch.setattr(ai.time, 'time', lambda: clock)
    for rows in (20, 21, 22):
        assert explain(gateway, {**PROFILE, 'rows': rows})['source'] == 'ai'
        clock += 1
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT COUNT(*) FROM ai_cache').fetchone()[0] == 2
    assert explain(gateway, {**PROFILE, 'rows': 20})['source'] == 'ai'
    assert len(provider.requests) == 8


def test_cache_is_bypassed_when_disabled_and_does_not_override_disabled_policy(db_path, provider):
    gateway = AIGateway(settings(), db_path)
    assert explain(gateway)['source'] == 'ai'
    assert explain(AIGateway(settings(ai_cache_enabled=False), db_path))['source'] == 'ai'
    assert explain(AIGateway(settings(ai_enabled=False), db_path))['reason'] == 'disabled'
    assert explain(AIGateway(settings(openrouter_model='paid/model'), db_path))['reason'] == 'model_not_allowed'
    assert len(provider.requests) == 4


def test_only_aggregate_counts_and_allowlisted_semantic_types_leave_process(db_path, provider, caplog):
    caplog.set_level(logging.DEBUG)
    sentinel = 'SECRET_COLUMN_RAW_SAMPLE_PRIVATE_PATH'
    profile = {
        **PROFILE,
        'filename': sentinel,
        'rows': True,
        'columns': 3,
        'missing_cells': sentinel,
        'total_cells': float('nan'),
        'duplicate_rows': -1,
        'empty_columns': [sentinel],
        'constant_columns': [sentinel],
        'type_distribution': {'numeric': 1, sentinel: 2, 'text': sentinel, 'date': True},
        'column_profiles': [{
            'name': sentinel, 'storage_type': sentinel, 'semantic_type': sentinel,
            'samples': [sentinel], 'common_values': [{'value': sentinel, 'count': 99999}],
            'numeric': {'mean': 987654321, 'min': 123456789, 'histogram': {'edges': [sentinel]}},
        }],
        'correlation': {'columns': [sentinel], 'matrix': [[987654321]]},
        'memory_bytes': sentinel,
        'prompt': sentinel,
    }
    gateway = AIGateway(settings(), db_path)
    assert explain(gateway, profile)['source'] == 'ai'
    raw = provider.requests[1].content.decode()
    assert sentinel not in raw
    assert TEST_KEY not in raw
    assert '987654321' not in raw
    assert '123456789' not in raw
    context = json.loads(json.loads(raw)['messages'][1]['content'])
    assert context == {
        'rows': 0, 'columns': 3, 'total_cells': 0, 'missing_cells': 0,
        'duplicate_rows': 0, 'empty_columns': 1, 'constant_columns': 1,
        'semantic_type_counts': {'numeric': 1, 'unknown': 2},
    }
    profile['column_profiles'] = [{'name': 'DIFFERENT_PRIVATE_VALUE', 'samples': ['other']}]
    assert explain(gateway, profile)['source'] == 'cache'
    assert len(provider.requests) == 2
    assert sentinel not in caplog.text
    assert TEST_KEY not in caplog.text


def test_summary_rejects_raw_numeric_strings_large_counts_and_nonfinite_values(db_path, provider):
    profile = {**PROFILE, 'rows': '123456', 'columns': 10**100, 'missing_cells': float('inf')}
    assert explain(AIGateway(settings(), db_path), profile)['source'] == 'ai'
    context = json.loads(json.loads(provider.requests[-1].content)['messages'][1]['content'])
    assert context['rows'] == context['columns'] == context['missing_cells'] == 0


def test_ai_tables_coexist_without_modifying_parent_tables(db_path):
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE parent_data(value TEXT)')
        db.execute("INSERT INTO parent_data VALUES ('unchanged')")
    AIGateway(settings(), db_path)
    AIGateway(settings(), db_path)
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT value FROM parent_data').fetchall() == [('unchanged',)]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {'parent_data', 'ai_usage', 'ai_cache'}


def test_unusable_database_keeps_deterministic_explanations_available(db_path, provider):
    db_path.mkdir()
    gateway = AIGateway(settings(), db_path)
    assert gateway.status()['reason'] == 'storage_unavailable'
    assert explain(gateway)['source'] == 'deterministic'
    assert explain(gateway)['reason'] == 'storage_unavailable'
    assert provider.requests == []


def test_failed_quota_storage_never_allows_network(db_path, provider):
    gateway = AIGateway(settings(ai_cache_enabled=False), db_path)
    with sqlite3.connect(db_path) as db:
        db.execute('DROP TABLE ai_usage')
    assert gateway.status()['reason'] == 'storage_unavailable'
    assert explain(gateway)['reason'] == 'storage_unavailable'
    assert provider.requests == []
