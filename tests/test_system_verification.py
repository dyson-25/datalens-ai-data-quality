"""Synthetic, isolated HTTP/storage verification; case IDs are documentation anchors."""
import csv
import io
import json
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.models import Operation


@pytest.fixture
def config(tmp_path):
    return Settings(_env_file=None, app_env='test', storage_root=tmp_path,
                    ai_enabled=False, openrouter_api_key='')


@pytest.fixture
def app_factory(config, monkeypatch):
    monkeypatch.setitem(Settings.model_config, 'env_file', None)
    monkeypatch.setenv('STORAGE_ROOT', str(config.storage_root / 'bootstrap'))
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('AI_ENABLED', 'false')
    from backend.main import create_app
    return create_app


@pytest.fixture
def client(config, app_factory):
    with TestClient(app_factory(config)) as test:
        yield test


def uploaded(client, content=b'name,amount\n Alice ,1\nBob,2\n Alice ,1\n', filename='synthetic.csv'):
    response = client.post('/api/v1/datasets/upload', files={'file': (filename, content)})
    assert response.status_code == 201, response.text
    info = response.json()
    return '/api/v1/datasets/' + info['dataset_id'], {'X-Session-Token': info['token']}, info


def poll(client, base, headers, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(base + '/jobs/' + job_id, headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        if result['status'] not in ('queued', 'running'):
            return result
        time.sleep(.005)
    pytest.fail('Job did not reach terminal state')


def ingested(client, content=b'name,amount\n Alice ,1\nBob,2\n Alice ,1\n'):
    base, headers, info = uploaded(client, content)
    response = client.post(base + '/ingest', headers=headers, json={})
    assert response.status_code == 202, response.text
    job = poll(client, base, headers, response.json()['job_id'])
    assert job['status'] == 'succeeded', job
    assert job['error'] is None
    return base, headers, info, job['result']


def revision(meta):
    return {'expected_version': meta['active_version'], 'expected_revision': meta['revision']}


def preview(client, base, headers, meta, operation=None):
    response = client.post(base + '/cleaning/preview', headers=headers, json={
        **revision(meta), 'operation': operation or {'kind': 'trim', 'column': 'name'}})
    assert response.status_code == 200, response.text
    return response.json()


def apply(client, base, headers, meta, pending):
    return client.post(base + '/cleaning/apply', headers=headers, json={
        **revision(meta), 'preview_id': pending['preview_id'], 'approved': True})


LIFECYCLES = [
    ('trim', b'x,y\n A ,1\nB,2\n', 'x', {}, ['A', 'B'], [0, 1]),
    ('normalize_missing', b'x,y\nNA,1\nOK,2\n', 'x', {'tokens': ['NA']}, [None, 'OK'], [0, 1]),
    ('drop_duplicates', b'x,y\nA,1\nA,1\nB,2\n', None, {'row_ids': [1]}, ['A', 'B'], [0, 2]),
    ('to_numeric', b'x,y\n001,1\nbad,2\n', 'x', {'coerce': True}, [1, None], [0, 1]),
    ('to_date', b'x,y\n2024-01-02,1\nbad,2\n', 'x', {'format': '%Y-%m-%d', 'coerce': True}, ['2024-01-02T00:00:00', None], [0, 1]),
    ('fill_missing', b'x,y\n1,1\n,2\n3,3\n', 'x', {'strategy': 'mean'}, [1, 2, 3], [0, 1, 2]),
    ('fill_missing', b'x,y\n1,1\n,2\n3,3\n', 'x', {'strategy': 'median'}, [1, 2, 3], [0, 1, 2]),
    ('fill_missing', b'x,y\nA,1\n,2\nA,3\n', 'x', {'strategy': 'mode'}, ['A', 'A', 'A'], [0, 1, 2]),
    ('fill_missing', b'x,y\nA,1\n,2\n', 'x', {'strategy': 'constant', 'value': 'filled'}, ['A', 'filled'], [0, 1]),
    ('drop_column', b'x,y\nA,1\nB,2\n', 'y', {}, ['A', 'B'], [0, 1]),
    ('case', b'x,y\nAb c,1\nDe F,2\n', 'x', {'mode': 'lower'}, ['ab c', 'de f'], [0, 1]),
    ('case', b'x,y\nAb c,1\nDe F,2\n', 'x', {'mode': 'upper'}, ['AB C', 'DE F'], [0, 1]),
    ('case', b'x,y\nab c,1\nde f,2\n', 'x', {'mode': 'title'}, ['Ab C', 'De F'], [0, 1]),
    ('map_categories', b'x,y\nA,1\nB,2\n', 'x', {'mapping': {'A': 'Alpha', 'B': None}}, ['Alpha', None], [0, 1]),
    ('handle_infinity', b'x,y\ninf,1\n-inf,2\n3,3\n', 'x', {}, [None, None, 3], [0, 1, 2]),
    ('outliers', b'x,y\n1,1\n100,2\n3,3\n', 'x', {'row_ids': [1], 'action': 'remove'}, [1, 3], [0, 2]),
    ('outliers', b'x,y\n1,1\n100,2\n3,3\n', 'x', {'row_ids': [1], 'action': 'clip', 'upper': 10}, [1, 10, 3], [0, 1, 2]),
]
LIFECYCLE_IDS = [f'LIFE-{i:02d}-{case[0]}' for i, case in enumerate(LIFECYCLES, 1)]


@pytest.mark.parametrize(('kind', 'source', 'column', 'params', 'values', 'row_ids'), LIFECYCLES, ids=LIFECYCLE_IDS)
def test_every_cleaning_lifecycle(client, kind, source, column, params, values, row_ids):
    if kind == 'handle_infinity':
        # CSV preserves infinity spellings as text; seed the supported numeric snapshot explicitly.
        base, headers, info = uploaded(client, source)
        frame = pd.DataFrame({'x': pd.array([float('inf'), -float('inf'), 3], dtype='Float64'),
                              'y': pd.array([1, 2, 3], dtype='Int64')},
                             index=pd.Index([0, 1, 2], name='__row_id__'))
        meta = client.app.state.store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    else:
        base, headers, info, meta = ingested(client, source)
    store, dataset_id = client.app.state.store, info['dataset_id']
    v0 = store.snapshot_path(dataset_id, 0).read_bytes()
    baseline = store.frame(dataset_id).copy(deep=True)
    pending = preview(client, base, headers, meta, {'kind': kind, 'column': column, 'params': params})
    assert pending['affected_rows'] > 0
    assert client.get(base, headers=headers).json() == meta
    assert store.snapshot_path(dataset_id, 0).read_bytes() == v0
    denied = client.post(base + '/cleaning/apply', headers=headers, json={
        **revision(meta), 'preview_id': pending['preview_id'], 'approved': False})
    assert denied.status_code == 422
    assert store.metadata(dataset_id) == meta
    response = apply(client, base, headers, meta, pending)
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed['active_version'] == 1 and changed['revision'] == meta['revision'] + 1
    v1 = store.snapshot_path(dataset_id, 1).read_bytes()
    rows = client.get(base + '/preview', headers=headers).json()
    assert [row['row_id'] for row in rows['rows']] == row_ids
    assert [row['values'][0] for row in rows['rows']] == values
    assert rows['columns'] == (['x'] if kind == 'drop_column' else ['x', 'y'])
    history = client.get(base + '/history', headers=headers).json()
    assert [item['parent'] for item in history['versions']] == [None, 0]
    assert history['versions'][1]['operation'] == {'kind': kind, 'column': column, 'params': params}
    assert apply(client, base, headers, changed, pending).status_code == 409
    for action, expected in [('undo', 0), ('redo', 1), ('reset', 0)]:
        result = client.post(base + '/' + action, headers=headers, json=revision(changed))
        assert result.status_code == 200, result.text
        changed = result.json()
        assert changed['active_version'] == expected
        assert changed['expires_at'] == meta['expires_at']
        assert client.get(base, headers=headers).status_code == 200
        assert store.snapshot_path(dataset_id, 0).read_bytes() == v0
        assert store.snapshot_path(dataset_id, 1).read_bytes() == v1
        if expected == 0:
            pd.testing.assert_frame_equal(store.frame(dataset_id), baseline)
    assert client.post(base + '/redo', headers=headers, json=revision(changed)).status_code == 409
    assert store.original(dataset_id)[0] == source
    assert client.get(base + '/history', headers=headers).json()['versions'] == history['versions']


def test_lifecycle_matrix_covers_all_allowed_operations():
    assert {case[0] for case in LIFECYCLES} == set(Operation.model_fields['kind'].annotation.__args__)


@pytest.mark.parametrize('approval', [1, 1.0, 'true', 'yes', None], ids=['APPROVAL-integer', 'APPROVAL-float', 'APPROVAL-string', 'APPROVAL-yes', 'APPROVAL-null'])
def test_approval_requires_json_boolean(client, approval):
    base, headers, info, meta = ingested(client)
    pending = preview(client, base, headers, meta)
    response = client.post(base + '/cleaning/apply', headers=headers, json={
        **revision(meta), 'preview_id': pending['preview_id'], 'approved': approval})
    assert response.status_code == 422
    assert client.get(base, headers=headers).json() == meta


def test_preview_exact_expiry_boundary(client, monkeypatch):
    base, headers, info, meta = ingested(client)
    pending = preview(client, base, headers, meta)
    store = client.app.state.store
    with store.db.connect() as db:
        expiry = db.execute('SELECT expires_at FROM previews WHERE id=?', (pending['preview_id'],)).fetchone()[0]
    monkeypatch.setattr('backend.store.time.time', lambda: expiry)
    response = apply(client, base, headers, meta, pending)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'stale_preview'
    assert store.metadata(info['dataset_id']) == meta


def test_pending_preview_replacement_navigation_and_cross_session(client):
    base, headers, info, meta = ingested(client)
    first = preview(client, base, headers, meta)
    second = preview(client, base, headers, meta)
    assert apply(client, base, headers, meta, first).status_code == 409
    other_base, other_headers, _, other_meta = ingested(client)
    assert apply(client, other_base, other_headers, other_meta, second).status_code == 409
    reset = client.post(base + '/reset', headers=headers, json=revision(meta))
    assert reset.status_code == 200
    reset_meta = reset.json()
    assert reset_meta['expires_at'] == meta['expires_at']
    assert apply(client, base, headers, reset_meta, second).status_code == 409
    pending = preview(client, base, headers, reset_meta)
    changed = apply(client, base, headers, reset_meta, pending).json()
    fresh = preview(client, base, headers, changed, {'kind': 'case', 'column': 'name', 'params': {'mode': 'upper'}})
    undone = client.post(base + '/undo', headers=headers, json=revision(changed)).json()
    assert apply(client, base, headers, undone, fresh).status_code == 409


AUTH_ROUTES = [
    ('GET', '', None), ('POST', '/ingest', {}), ('GET', '/jobs/{job}', None),
    ('GET', '/preview', None), ('GET', '/profile', None), ('GET', '/columns/name', None),
    ('GET', '/quality', None), ('POST', '/quality', {'domain_rules': {'amount': {'min': 0}}}),
    ('GET', '/recommendations', None), ('POST', '/anomalies', {'columns': ['amount']}),
    ('POST', '/cleaning/preview', {'operation': {'kind': 'trim', 'column': 'name'}}),
    ('POST', '/cleaning/apply', {'approved': True, 'preview_id': '0' * 36}),
    ('POST', '/undo', {}), ('POST', '/redo', {}), ('POST', '/reset', {}),
    ('POST', '/restore', {'version': 0}), ('GET', '/history', None),
    ('GET', '/export?format=csv', None), ('GET', '/export?format=xlsx', None),
    ('GET', '/report?format=json', None), ('GET', '/report?format=html', None),
    ('GET', '/code?language=python', None), ('GET', '/code?language=sql', None),
    ('POST', '/ai/explain', {}), ('DELETE', '', None),
]


def test_all_capability_routes_isolate_sessions_expire_and_cascade(client, monkeypatch):
    base, headers, info, meta = ingested(client)
    other_base, other_headers, other_info, _ = ingested(client)
    store = client.app.state.store
    preview(client, base, headers, meta)
    assert client.get(base + '/profile', headers=headers).status_code == 200
    with store.db.connect() as db:
        job_id = db.execute('SELECT id FROM jobs WHERE dataset_id=?', (info['dataset_id'],)).fetchone()[0]
    for method, suffix, body in AUTH_ROUTES:
        if body is not None and suffix in {'/cleaning/preview', '/cleaning/apply', '/undo', '/redo', '/reset', '/restore'}:
            body = {**revision(meta), **body}
        path = base + suffix.replace('{job}', job_id)
        for token in ({}, {'X-Session-Token': 'wrong'}, other_headers):
            response = client.request(method, path, headers=token, json=body)
            assert response.status_code == 404, (method, suffix, response.text)
            assert response.json()['error']['code'] == 'not_found'
    assert client.get(other_base + '/jobs/' + job_id, headers=other_headers).status_code == 404
    monkeypatch.setattr('backend.store.time.time', lambda: meta['expires_at'])
    for method, suffix, body in AUTH_ROUTES:
        if body is not None and suffix in {'/cleaning/preview', '/cleaning/apply', '/undo', '/redo', '/reset', '/restore'}:
            body = {**revision(meta), **body}
        response = client.request(method, base + suffix.replace('{job}', job_id), headers=headers, json=body)
        assert response.status_code == 410, (method, suffix, response.text)
        assert response.json()['error']['code'] == 'expired'
    store.cleanup()
    assert not store.folder(info['dataset_id']).exists()
    for table in ('datasets', 'versions', 'profiles', 'previews', 'jobs'):
        key = 'id' if table == 'datasets' else 'dataset_id'
        with store.db.connect() as db:
            assert db.execute(f'SELECT count(*) FROM {table} WHERE {key}=?', (info['dataset_id'],)).fetchone()[0] == 0
    assert client.get(base, headers=headers).status_code == 404
    assert client.get(other_base, headers=other_headers).status_code == 200
    assert store.folder(other_info['dataset_id']).exists()


def test_restart_preserves_preview_snapshots_history_profiles_and_redo(config, app_factory):
    with TestClient(app_factory(config)) as first:
        base, headers, info, meta = ingested(first)
        profile = first.get(base + '/profile', headers=headers).json()
        pending = preview(first, base, headers, meta)
        source = first.app.state.store.original(info['dataset_id'])[0]
    with TestClient(app_factory(config)) as second:
        assert second.get(base, headers=headers).json() == meta
        assert second.get(base + '/profile', headers=headers).json() == profile
        result = apply(second, base, headers, meta, pending)
        assert result.status_code == 200
        changed = result.json()
        undone = second.post(base + '/undo', headers=headers, json=revision(changed)).json()
        history = second.get(base + '/history', headers=headers).json()['versions']
    with TestClient(app_factory(config)) as third:
        result = third.post(base + '/redo', headers=headers, json=revision(undone))
        assert result.status_code == 200 and result.json()['active_version'] == 1
        assert third.get(base + '/history', headers=headers).json()['versions'] == history
        assert third.app.state.store.original(info['dataset_id'])[0] == source
        assert third.get(base + '/preview', headers=headers).json()['rows'][0]['values'][0] == 'Alice'


@pytest.mark.parametrize(('suffix', 'media', 'name'), [
    ('/export?format=csv', 'text/csv', 'synthetic-v0.csv'),
    ('/export?format=xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'synthetic-v0.xlsx'),
    ('/report?format=json', 'application/json', 'synthetic-v0.json'),
    ('/report?format=html', 'text/html', 'synthetic-v0.html'),
    ('/code?language=python', 'text/plain', 'synthetic-v0.py'),
    ('/code?language=sql', 'text/plain', 'synthetic-v0.sql'),
], ids=['DOWNLOAD-csv', 'DOWNLOAD-xlsx', 'DOWNLOAD-json', 'DOWNLOAD-html', 'DOWNLOAD-python', 'DOWNLOAD-sql'])
def test_download_headers_are_truthful(client, suffix, media, name):
    base, headers, _, _ = ingested(client)
    response = client.get(base + suffix, headers=headers)
    assert response.status_code == 200 and response.content
    assert response.headers['content-type'].split(';')[0] == media
    assert response.headers['content-disposition'] == f'attachment; filename="{name}"'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    if name.endswith('.csv'):
        assert list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')))) == [
            ['name', 'amount'], [' Alice ', '1'], ['Bob', '2'], [' Alice ', '1']]
    elif name.endswith('.xlsx'):
        frame = pd.read_excel(io.BytesIO(response.content))
        assert frame['name'].tolist() == [' Alice ', 'Bob', ' Alice ']
        assert frame['amount'].tolist() == [1, 2, 1]
    elif name.endswith('.json'):
        report = response.json()
        assert report['profile']['rows'] == 3 and report['history']['active_version'] == 0
    elif name.endswith('.html'):
        assert response.text.startswith('<!doctype html>') and '<script' not in response.text
    elif name.endswith('.py'):
        compile(response.text, '<downloaded-reference>', 'exec')
        assert 'def replay(baseline):' in response.text
    else:
        assert 'PostgreSQL reference only' in response.text and 'ROLLBACK;' in response.text


DOWNLOADS = [
    ('/export?format=csv', 'csv'), ('/export?format=xlsx', 'xlsx'),
    ('/report?format=json', 'json'), ('/report?format=html', 'html'),
    ('/code?language=python', 'py'), ('/code?language=sql', 'sql'),
]


@pytest.mark.parametrize(('route', 'extension'), DOWNLOADS, ids=lambda item: item)
def test_download_filename_tracks_navigation_and_stale_auth(client, monkeypatch, route, extension):
    base, headers, info, cached = ingested(client)
    pending = preview(client, base, headers, cached)
    # A second capability holder changes the active snapshot without updating this client's cache.
    other = TestClient(client.app)
    try:
        response = apply(other, base, headers, cached, pending)
        assert response.status_code == 200
        current = response.json()
        for action, expected in [(None, 1), ('undo', 0), ('redo', 1), ('reset', 0), ('restore', 1)]:
            if action:
                body = revision(current)
                if action == 'restore':
                    body['version'] = 1
                response = other.post(base + '/' + action, headers=headers, json=body)
                assert response.status_code == 200, response.text
                current = response.json()
            response = client.get(base + route, headers=headers)
            assert response.status_code == 200, response.text
            assert response.headers['content-disposition'] == f'attachment; filename="synthetic-v{expected}.{extension}"'
            if extension == 'csv':
                assert list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))[1][0] == ('Alice' if expected else ' Alice ')
            elif extension == 'xlsx':
                assert pd.read_excel(io.BytesIO(response.content)).iloc[0, 0] == ('Alice' if expected else ' Alice ')
            elif extension == 'json':
                assert response.json()['history']['active_version'] == expected
            elif extension == 'py':
                assert ('"kind": "trim"' in response.text) == bool(expected)
            elif extension == 'sql':
                assert ('btrim(' in response.text) == bool(expected)
            else:
                assert f'&quot;active_version&quot;: {expected}' in response.text
        assert cached['active_version'] == 0
        store = client.app.state.store
        authorize = store.authorize

        def authorization_before_navigation(dataset_id, token):
            authenticated = authorize(dataset_id, token)
            with store.work():
                store.navigate(dataset_id, 'reset', current['active_version'], current['revision'])
            return authenticated

        monkeypatch.setattr(store, 'authorize', authorization_before_navigation)
        response = client.get(base + route, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers['content-disposition'] == f'attachment; filename="synthetic-v0.{extension}"'
        assert store.metadata(info['dataset_id'])['active_version'] == 0
    finally:
        other.close()


@pytest.mark.parametrize(('route', 'extension'), DOWNLOADS, ids=lambda item: item)
def test_download_metadata_and_bytes_share_processing_lock(client, monkeypatch, route, extension):
    base, headers, _, _ = ingested(client)
    store = client.app.state.store
    with store.work():
        response = client.get(base + route, headers=headers)
        assert response.status_code == 429
        assert 'content-disposition' not in response.headers
    metadata = store.metadata

    def locked_metadata(dataset_id):
        acquired = store.gate.acquire(blocking=False)
        if acquired:
            store.gate.release()
        assert not acquired, 'Download read metadata outside the snapshot processing lock'
        return metadata(dataset_id)

    monkeypatch.setattr(store, 'metadata', locked_metadata)
    response = client.get(base + route, headers=headers)
    assert response.status_code == 200 and response.content
    assert response.headers['content-disposition'] == f'attachment; filename="synthetic-v0.{extension}"'


@pytest.mark.parametrize(('route', 'extension'), DOWNLOADS, ids=lambda item: item)
def test_download_without_snapshot_is_not_a_versioned_success(client, route, extension):
    base, headers, _ = uploaded(client)
    response = client.get(base + route, headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()['error']['code'] == 'not_ingested'
    assert 'content-disposition' not in response.headers


@pytest.mark.parametrize(('source', 'stem'), [
    (r'C:\private\source.csv', 'source'), ('../../nested/name.csv', 'name'),
    ('bad\r\n"name.csv', 'bad___name'), ('bad<>:|?*.csv', 'bad______'),
    ('safe\x00\u202ename.csv', 'safe__name'), ('...csv', 'dataset'),
    ('résumé 東京.csv', 'résumé 東京'), ('sales.report.final.csv', 'sales.report.final'),
    ('東' * 196 + '.csv', '東' * 66),
], ids=['NAME-windows-path', 'NAME-posix-path', 'NAME-header-controls', 'NAME-filesystem',
        'NAME-null-bidi', 'NAME-empty', 'NAME-unicode', 'NAME-multi-dot', 'NAME-unicode-length'])
def test_download_sanitizes_persisted_source_filename(client, source, stem):
    base, headers, info, _ = ingested(client)
    store = client.app.state.store
    # Seed metadata directly so multipart escaping cannot hide unsafe persisted names.
    with store.db.connect() as db:
        db.execute('UPDATE datasets SET filename=? WHERE id=?', (source, info['dataset_id']))
    for route, extension in DOWNLOADS:
        response = client.get(base + route, headers=headers)
        assert response.status_code == 200, response.text
        name = f'{stem}-v0.{extension}'
        fallback = name.encode('ascii', 'replace').decode().replace('?', '_')
        expected = f'attachment; filename="{fallback}"'
        if name != fallback:
            expected += "; filename*=UTF-8''" + quote(name, safe='')
        assert response.headers['content-disposition'] == expected
        assert response.headers['content-disposition'].isascii()
        assert '\r' not in expected and '\n' not in expected and '\x00' not in expected
    assert store.metadata(info['dataset_id'])['filename'] == source


@pytest.mark.parametrize(('filename', 'content'), [
    ('empty.csv', b''), ('binary.csv', b'\x00\x01\x02'), ('broken.xlsx', b'not a workbook'),
    ('bad.exe', b'a\n1\n'),
], ids=['UPLOAD-empty', 'UPLOAD-binary', 'UPLOAD-workbook', 'UPLOAD-extension'])
def test_invalid_upload_leaves_no_session(client, filename, content):
    response = client.post('/api/v1/datasets/upload', files={'file': (filename, content)})
    assert response.status_code == 422, response.text
    assert 'error' in response.json()
    store = client.app.state.store
    assert not list(store.sessions.iterdir())
    with store.db.connect() as db:
        assert db.execute('SELECT count(*) FROM datasets').fetchone()[0] == 0


@pytest.mark.parametrize(('suffix', 'body'), [
    ('/ingest', {'unknown': 'PRIVATE_INPUT'}), ('/anomalies', {'columns': []}),
    ('/anomalies', {'columns': ['amount'], 'threshold': 'Infinity'}),
    ('/quality', {'domain_rules': {'amount': {'min': 2, 'max': 1}}}),
    ('/ai/explain', {'prompt': 'PRIVATE_INPUT'}),
    ('/cleaning/preview', {'expected_version': 0, 'expected_revision': 1, 'operation': {'kind': 'not_allowed'}}),
], ids=['VALIDATE-ingest', 'VALIDATE-columns', 'VALIDATE-threshold', 'VALIDATE-bounds', 'VALIDATE-ai', 'VALIDATE-operation'])
def test_invalid_bodies_are_redacted_and_nonmutating(client, suffix, body):
    base, headers, _, meta = ingested(client)
    response = client.post(base + suffix, headers=headers, json=body)
    assert response.status_code == 422
    assert 'PRIVATE_INPUT' not in response.text
    assert client.get(base, headers=headers).json() == meta


def test_public_routes_samples_schema_and_request_boundaries(client):
    assert client.get('/').status_code == 200
    assert client.get('/docs').status_code == 200
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/api/v1/health').json() == {'status': 'ok', 'app_env': 'test'}
    assert client.get('/api/v1/ai/status').json()['reason'] == 'disabled'
    schema = client.get('/openapi.json').json()
    assert len(schema['paths']) >= 25
    samples = client.get('/api/v1/samples').json()['samples']
    assert samples
    for item in samples:
        response = client.post('/api/v1/datasets/sample/' + item['id'])
        if item['id'] == 'malformed':
            assert response.status_code == 422 and 'error' in response.json()
        else:
            assert response.status_code == 201, (item['id'], response.text)
            assert response.json()['active_version'] is None
    assert client.post('/api/v1/datasets/sample/unknown').status_code == 404
    assert client.post('/api/v1/datasets/upload').status_code == 422
    assert client.post('/api/v1/datasets/upload', content=b'x', headers={'Content-Length': 'invalid'}).status_code == 413
    base, headers, _, meta = ingested(client)
    for suffix in ('/preview?offset=-1', '/preview?limit=201', '/export?format=pdf', '/report?format=csv', '/code?language=bash'):
        assert client.get(base + suffix, headers=headers).status_code == 422
    assert client.get(base + '/preview?offset=99', headers=headers).json()['rows'] == []
    assert client.get(base + '/columns/missing', headers=headers).status_code == 404
    assert client.get(base + '/jobs/' + str(uuid4()), headers=headers).status_code == 404
    assert client.post(base + '/restore', headers=headers, json={**revision(meta), 'version': 999}).status_code == 404
    assert client.post(base + '/undo', headers=headers, json=revision(meta)).status_code == 409
    assert client.post(base + '/redo', headers=headers, json=revision(meta)).status_code == 409
    assert client.post(base + '/ingest', headers=headers, json={}).status_code == 409
    for method in ('iqr', 'mad'):
        response = client.post(base + '/anomalies', headers=headers, json={'columns': ['amount'], 'method': method})
        assert response.status_code == 200, response.text
    assert client.post(base + '/anomalies', headers=headers, json={
        'columns': ['amount'], 'method': 'isolation_forest'}).status_code == 422
    assert client.get(base, headers=headers).json() == meta
    numeric_base, numeric_headers, _, _ = ingested(client, b'x,y\n1,2\n2,3\n3,4\n4,5\n5,6\n100,200\n')
    assert client.post(numeric_base + '/anomalies', headers=numeric_headers, json={
        'columns': ['x', 'y'], 'method': 'isolation_forest'}).status_code == 200


@pytest.mark.parametrize(('failure', 'status'), [(ValueError('Invalid synthetic input'), 'failed'),
    (RuntimeError('PRIVATE_INTERNAL_DETAILS'), 'failed'), (TimeoutError(), 'timed_out')],
    ids=['JOB-validation', 'JOB-unexpected', 'JOB-timeout'])
def test_job_terminal_failure_does_not_publish_and_slot_recovers(client, monkeypatch, failure, status):
    from backend import ingestion
    base, headers, info = uploaded(client)
    original = ingestion.load_file

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(ingestion, 'load_file', fail)
    response = client.post(base + '/ingest', headers=headers, json={})
    assert response.status_code == 202
    job = poll(client, base, headers, response.json()['job_id'])
    assert job['status'] == status and job['result'] is None
    assert 'PRIVATE_INTERNAL_DETAILS' not in job['error']
    assert client.get(base, headers=headers).json()['active_version'] is None
    store = client.app.state.store
    assert not store.snapshot_path(info['dataset_id'], 0).exists()
    assert store.original(info['dataset_id'])[0]
    monkeypatch.setattr(ingestion, 'load_file', original)
    retry = client.post(base + '/ingest', headers=headers, json={})
    assert poll(client, base, headers, retry.json()['job_id'])['status'] == 'succeeded'


def test_running_job_reports_busy_without_mutating_other_session(client, monkeypatch):
    from backend import ingestion
    base, headers, _ = uploaded(client)
    other_base, other_headers, _ = uploaded(client)
    started, release = threading.Event(), threading.Event()
    original = ingestion.load_file

    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(ingestion, 'load_file', blocked)
    response = client.post(base + '/ingest', headers=headers, json={})
    assert response.status_code == 202
    try:
        assert started.wait(5)
        job = client.get(base + '/jobs/' + response.json()['job_id'], headers=headers).json()
        assert job['status'] == 'running' and job['result'] is None
        assert client.post(other_base + '/ingest', headers=other_headers, json={}).status_code == 429
        assert client.delete(other_base, headers=other_headers).status_code == 429
        assert client.get(other_base, headers=other_headers).json()['active_version'] is None
    finally:
        release.set()
    assert poll(client, base, headers, response.json()['job_id'])['status'] == 'succeeded'


def test_executor_submission_failure_has_no_ghost_queued_job(client, monkeypatch):
    base, headers, info = uploaded(client)
    jobs = client.app.state.jobs

    def reject(*args, **kwargs):
        raise RuntimeError('executor unavailable')

    monkeypatch.setattr(jobs.executor, 'submit', reject)
    with pytest.raises(RuntimeError, match='executor unavailable'):
        jobs.submit_ingestion(info['dataset_id'], {})
    errors = TestClient(client.app, raise_server_exceptions=False)
    try:
        response = errors.post(base + '/ingest', headers=headers, json={})
    finally:
        errors.close()
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'internal_error'
    assert 'executor unavailable' not in response.text
    with jobs.store.db.connect() as db:
        rows = db.execute('SELECT status,error,completed_at FROM jobs WHERE dataset_id=?', (info['dataset_id'],)).fetchall()
    assert len(rows) == 2
    assert all(row['status'] == 'failed' and row['error'] and row['completed_at'] for row in rows)
    with jobs.store.work():
        assert jobs.store.metadata(info['dataset_id'])['active_version'] is None


def test_restart_cleanup_and_rollback_on_capacity_failure(client, monkeypatch, app_factory):
    base, headers, info, meta = ingested(client)
    store = client.app.state.store
    pending = preview(client, base, headers, meta)
    snapshot = store.snapshot_path(info['dataset_id'], 0).read_bytes()
    original = store.check_capacity

    def full(*args):
        from backend.store import StoreError
        raise StoreError('Synthetic full storage', 413, 'capacity')

    monkeypatch.setattr(store, 'check_capacity', full)
    response = apply(client, base, headers, meta, pending)
    assert response.status_code == 413
    assert store.metadata(info['dataset_id']) == meta
    assert store.snapshot_path(info['dataset_id'], 0).read_bytes() == snapshot
    assert not list(store.folder(info['dataset_id']).glob('snapshots/*.pending'))
    assert not store.snapshot_path(info['dataset_id'], 1).exists()
    monkeypatch.setattr(store, 'check_capacity', original)
    assert apply(client, base, headers, meta, pending).status_code == 200
    with store.db.connect() as db:
        db.execute('UPDATE datasets SET expires_at=0 WHERE id=?', (info['dataset_id'],))
    with TestClient(app_factory(store.settings)) as restarted:
        assert restarted.get(base, headers=headers).status_code == 404
        assert not store.folder(info['dataset_id']).exists()


def test_ai_http_fallback_and_mocked_success_are_explicit(client, monkeypatch):
    from backend import ai
    base, headers, _, meta = ingested(client)
    result = client.post(base + '/ai/explain', headers=headers, json={})
    assert result.status_code == 200 and result.json()['source'] == 'deterministic'
    assert result.json()['reason'] == 'disabled'
    settings = client.app.state.settings
    from pydantic import SecretStr
    settings.ai_enabled = True
    settings.openrouter_api_key = SecretStr('')
    client.app.state.ai = ai.AIGateway(settings, client.app.state.store.db.path)
    assert client.post(base + '/ai/explain', headers=headers, json={}).json()['reason'] == 'missing_key'
    settings.openrouter_api_key = SecretStr('synthetic-test-only')
    requests = []

    def provider(request):
        requests.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'data': [{'id': ai.FREE_MODEL, 'pricing': {'prompt': '0', 'completion': '0'}}]})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
            'content': json.dumps({'explanation': 'Human review is required.', 'warnings': []})}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(ai.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs))
    result = client.post(base + '/ai/explain', headers=headers, json={})
    assert result.status_code == 200 and result.json()['source'] == 'ai'
    assert result.json()['reason'] is None and len(requests) == 2
    assert 'Alice' not in requests[-1].content.decode() and 'amount' not in requests[-1].content.decode()
    assert client.post(base + '/ai/explain', headers=headers, json={}).json()['source'] == 'cache'
    assert len(requests) == 2
    assert client.get(base, headers=headers).json() == meta


def test_real_elapsed_job_deadline_never_publishes(client, monkeypatch):
    from backend import ingestion
    base, headers, info = uploaded(client)
    client.app.state.settings.job_timeout_seconds = 1
    original = ingestion.load_file

    def slow(*args, **kwargs):
        frame = original(*args, **kwargs)
        time.sleep(1.05)
        return frame

    monkeypatch.setattr(ingestion, 'load_file', slow)
    response = client.post(base + '/ingest', headers=headers, json={})
    job = poll(client, base, headers, response.json()['job_id'])
    assert job['status'] == 'timed_out' and job['result'] is None
    assert client.get(base, headers=headers).json()['active_version'] is None
    assert not client.app.state.store.snapshot_path(info['dataset_id'], 0).exists()


def test_upload_actual_body_limit_and_mutation_body_limit(client):
    client.app.state.settings.max_upload_mb = 1
    response = client.post('/api/v1/datasets/upload', files={'file': ('large.csv', b'x' * (1024 * 1024 + 1))})
    assert response.status_code == 413 and response.json()['error']['code'] == 'too_large'
    assert not list(client.app.state.store.sessions.iterdir())
    base, headers, info = uploaded(client)
    response = client.post(base + '/ingest', headers=headers, content=b' ' * 65537)
    assert response.status_code == 413
    assert client.get(base, headers=headers).json()['active_version'] is None


def test_chunked_request_body_limit_is_enforced(client):
    from backend.main import BodyLimitMiddleware
    import asyncio

    async def exercise():
        messages = iter([{'type': 'http.request', 'body': b'x' * 40000, 'more_body': True},
                         {'type': 'http.request', 'body': b'x' * 40000, 'more_body': False}])
        observed = []

        async def receive():
            return next(messages)

        async def send(message):
            observed.append(message)

        async def app(scope, receive, send):
            from starlette.exceptions import HTTPException
            await receive()
            with pytest.raises(HTTPException) as error:
                await receive()
            assert error.value.status_code == 413

        await BodyLimitMiddleware(app, 1024)({'type': 'http', 'path': '/api/v1/x', 'headers': []}, receive, send)
        assert observed == []

    asyncio.run(exercise())


def test_uningested_dataset_errors_and_delete_cascades(client):
    base, headers, info = uploaded(client)
    for suffix in ('/preview', '/profile', '/quality', '/recommendations', '/columns/name', '/export', '/report'):
        response = client.get(base + suffix, headers=headers)
        assert response.status_code == 409, (suffix, response.text)
        assert response.json()['error']['code'] == 'not_ingested'
    assert client.post(base + '/ai/explain', headers=headers, json={}).status_code == 409
    assert client.delete(base, headers=headers).json() == {'deleted': True}
    assert client.delete(base, headers=headers).status_code == 404
    assert not client.app.state.store.folder(info['dataset_id']).exists()


def test_public_limits_docs_and_rate_limit(config, app_factory):
    config.app_env = 'public'
    with TestClient(app_factory(config)) as public:
        assert public.get('/docs').status_code == 404
        for _ in range(120):
            assert public.get('/api/v1/health').status_code == 200
        rejected = public.get('/api/v1/health')
        assert rejected.status_code == 429
        assert rejected.json()['error']['code'] == 'rate_limit'
        assert rejected.headers['retry-after'] == '60'
        assert public.get('/').status_code == 200


@pytest.mark.parametrize('mode', ['public', 'cloud'])
def test_config_environment_limits_are_bounded(tmp_path, mode):
    settings = Settings(_env_file=None, app_env=mode, storage_root=tmp_path, ai_enabled=False,
                        max_upload_mb=25, max_rows=200000, max_columns=500, max_sessions=200,
                        max_storage_mb=4096)
    assert settings.max_upload_mb == 5
    assert settings.max_rows == 10000 and settings.max_columns == 50
    assert settings.max_sessions == 10 and settings.max_storage_mb == 256
    assert settings.limits['max_uncompressed_bytes'] == 30 * 1024 * 1024


@pytest.mark.parametrize(('response_kind', 'reason'), [('network', 'provider_error'), ('malformed', 'invalid_response')],
                         ids=['AIHTTP-network', 'AIHTTP-malformed'])
def test_ai_http_failures_are_deterministic_not_success(client, monkeypatch, response_kind, reason):
    from backend import ai
    from pydantic import SecretStr
    base, headers, _, meta = ingested(client)
    settings = client.app.state.settings
    settings.ai_enabled = True
    settings.openrouter_api_key = SecretStr('synthetic-test-only')
    settings.ai_max_retries = 0
    client.app.state.ai = ai.AIGateway(settings, client.app.state.store.db.path)
    calls = []

    def provider(request):
        calls.append(request)
        if response_kind == 'network':
            raise httpx.ConnectError('SYNTHETIC_PRIVATE_PROVIDER_DETAILS')
        if request.method == 'GET':
            return httpx.Response(200, json={'data': [{'id': ai.FREE_MODEL, 'pricing': {'prompt': '0', 'completion': '0'}}]})
        return httpx.Response(200, content=b'{"SYNTHETIC_PRIVATE_PROVIDER_DETAILS":true}')

    original_client = httpx.AsyncClient
    monkeypatch.setattr(ai.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs))
    response = client.post(base + '/ai/explain', headers=headers, json={})
    assert response.status_code == 200
    assert response.json()['source'] == 'deterministic' and response.json()['reason'] == reason
    assert 'SYNTHETIC_PRIVATE_PROVIDER_DETAILS' not in response.text
    assert response.json()['warnings'] and calls
    assert client.get(base, headers=headers).json() == meta
