import hashlib
import io
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, app_env='test', storage_root=tmp_path, ai_enabled=False)
    with TestClient(create_app(settings)) as test:
        yield test


def upload(client, content=b'name,amount\n Alice ,1\nBob,2\n Alice ,1\n', filename='sample.csv'):
    response = client.post('/api/v1/datasets/upload', files={'file': (filename, content)})
    assert response.status_code == 201, response.text
    info = response.json()
    headers = {'X-Session-Token': info['token']}
    return info, headers


def ingest(client, info, headers, **options):
    base = f"/api/v1/datasets/{info['dataset_id']}"
    response = client.post(base + '/ingest', json=options, headers=headers)
    assert response.status_code == 202, response.text
    for _ in range(500):
        job = client.get(base + '/jobs/' + response.json()['job_id'], headers=headers).json()
        if job['status'] not in {'queued', 'running'}:
            assert job['status'] == 'succeeded', job
            return base, job['result']
        time.sleep(0.01)
    pytest.fail('Ingestion job did not finish')


def version(meta):
    return {'expected_version': meta['active_version'], 'expected_revision': meta['revision']}


def apply_trim(client, base, headers, meta):
    preview = client.post(base + '/cleaning/preview', headers=headers, json={
        **version(meta), 'operation': {'kind': 'trim', 'column': 'name', 'params': {}}})
    assert preview.status_code == 200, preview.text
    assert preview.json()['affected_rows'] == 2
    result = client.post(base + '/cleaning/apply', headers=headers, json={
        **version(meta), 'approved': True, 'preview_id': preview.json()['preview_id']})
    assert result.status_code == 200, result.text
    return result.json(), preview.json()


def test_health_and_request_validation(client):
    assert client.get('/api/v1/health').json()['status'] == 'ok'
    response = client.post('/api/v1/datasets/upload', files={'file': ('evil.exe', b'abc')})
    assert response.status_code == 422
    assert 'error' in response.json()
    assert client.get('/api/v1/health').headers['x-content-type-options'] == 'nosniff'


def test_offline_api_documentation_and_schema(client):
    response = client.get('/docs')
    assert response.status_code == 200
    assert '/static/api-docs.js' in response.text
    assert 'cdn.jsdelivr.net' not in response.text
    schema = client.get('/openapi.json').json()
    assert 'post' in schema['paths']['/api/v1/datasets/{dataset_id}/quality']


def test_explicit_domain_rules_are_validated_and_non_mutating(client):
    info, headers = upload(client, b'amount\n1\n50\n100\n')
    base, meta = ingest(client, info, headers)
    normal = client.get(base + '/quality', headers=headers).json()['issues']
    checked = client.post(base + '/quality', headers=headers, json={'domain_rules': {'amount': {'min': 0, 'max': 60}}})
    assert checked.status_code == 200, checked.text
    assert len(checked.json()['issues']) > len(normal)
    assert client.get(base, headers=headers).json() == meta
    assert client.post(base + '/quality', json={'domain_rules': {'amount': {'min': 0}}}).status_code == 404
    for rules in ({}, {'amount': {}}, {'amount': {'min': 2, 'max': 1}}, {'amount': {'max': 'Infinity'}}, {'unknown': {'min': 0}}):
        response = client.post(base + '/quality', headers=headers, json={'domain_rules': rules})
        assert response.status_code == 422, response.text


def test_end_to_end_versions_reports_exports(client):
    info, headers = upload(client)
    base, meta = ingest(client, info, headers)
    store = client.app.state.store
    original, _ = store.original(info['dataset_id'])
    digest = hashlib.sha256(original).hexdigest()
    profile = client.get(base + '/profile', headers=headers)
    assert profile.status_code == 200, profile.text
    assert profile.json()['rows'] == 3
    assert profile.json()['duplicate_rows'] == 1
    assert client.get(base + '/quality', headers=headers).json()['issues']
    assert client.get(base + '/recommendations', headers=headers).json()['recommendations']
    assert client.get(base + '/columns/name', headers=headers).status_code == 200
    new_meta, preview = apply_trim(client, base, headers, meta)
    assert new_meta['active_version'] == 1
    assert store.frame(info['dataset_id'], 0).iloc[0]['name'] == ' Alice '
    assert client.get(base + '/preview', headers=headers).json()['rows'][0]['values'][0] == 'Alice'
    assert client.post(base + '/cleaning/apply', headers=headers, json={**version(meta), 'approved': True, 'preview_id': preview['preview_id']}).status_code == 409
    undone = client.post(base + '/undo', headers=headers, json=version(new_meta)).json()
    assert undone['active_version'] == 0
    redone = client.post(base + '/redo', headers=headers, json=version(undone)).json()
    assert redone['active_version'] == 1
    restored = client.post(base + '/restore', headers=headers, json={**version(redone), 'version': 0}).json()
    assert restored['active_version'] == 0
    branch, _ = apply_trim(client, base, headers, restored)
    assert branch['active_version'] == 2
    history = client.get(base + '/history', headers=headers).json()
    assert [v['parent'] for v in history['versions']] == [None, 0, 0]
    assert client.post(base + '/redo', headers=headers, json=version(branch)).status_code == 409
    for format in ('csv', 'xlsx'):
        exported = client.get(base + '/export', params={'format': format}, headers=headers)
        assert exported.status_code == 200
        reader = pd.read_csv if format == 'csv' else pd.read_excel
        frame = reader(io.BytesIO(exported.content))
        assert list(frame.columns) == ['name', 'amount']
        assert frame.iloc[0]['name'] == 'Alice'
    for format in ('json', 'html'):
        response = client.get(base + '/report', params={'format': format}, headers=headers)
        assert response.status_code == 200, response.text
    report = client.get(base + '/report', params={'format': 'json'}, headers=headers).json()
    assert report['profile'] == client.get(base + '/profile', headers=headers).json()
    assert report['issues'] == client.get(base + '/quality', headers=headers).json()['issues']
    assert report['history'] == client.get(base + '/history', headers=headers).json()
    for language in ('python', 'sql'):
        assert client.get(base + '/code', params={'language': language}, headers=headers).status_code == 200
    assert hashlib.sha256(store.original(info['dataset_id'])[0]).hexdigest() == digest
    reset = client.post(base + '/reset', headers=headers, json=version(branch)).json()
    assert reset['active_version'] == 0
    assert client.post(base + '/ai/explain', headers=headers, json={}).json()['source'] == 'deterministic'


def test_preview_isolation_and_approval(client):
    info, headers = upload(client)
    base, meta = ingest(client, info, headers)
    path = client.app.state.store.snapshot_path(info['dataset_id'], 0)
    before = path.read_bytes()
    response = client.post(base + '/cleaning/preview', headers=headers, json={**version(meta), 'operation': {'kind': 'trim', 'column': 'name'}})
    assert response.status_code == 200
    assert path.read_bytes() == before
    assert client.get(base, headers=headers).json() == meta
    payload = {**version(meta), 'approved': False, 'preview_id': response.json()['preview_id']}
    assert client.post(base + '/cleaning/apply', headers=headers, json=payload).status_code == 422
    bad = client.post(base + '/cleaning/preview', headers=headers, json={**version(meta), 'operation': {'kind': 'arbitrary_code', 'params': {'code': 'secret'}}})
    assert bad.status_code == 422 and 'secret' not in bad.text


def test_session_isolation_every_endpoint(client):
    first, headers = upload(client)
    base, meta = ingest(client, first, headers)
    second, other = upload(client)
    for suffix in ('', '/profile', '/preview', '/quality', '/recommendations', '/history', '/export', '/report', '/code', '/columns/name', '/jobs/unknown'):
        assert client.get(base + suffix, headers=other).status_code == 404, suffix
        assert client.get(base + suffix).status_code == 404, suffix
    for suffix, body in [('/ingest', {}), ('/anomalies', {'columns': ['amount']}), ('/cleaning/preview', {**version(meta), 'operation': {'kind': 'trim'}}), ('/cleaning/apply', {**version(meta), 'approved': True, 'preview_id': '0'*36}), ('/undo', version(meta)), ('/redo', version(meta)), ('/reset', version(meta)), ('/restore', {**version(meta), 'version': 0}), ('/ai/explain', {})]:
        assert client.post(base + suffix, headers=other, json=body).status_code == 404, suffix
    assert client.delete(base, headers=other).status_code == 404
    assert client.delete(base, headers=headers).status_code == 200
    assert not client.app.state.store.folder(first['dataset_id']).exists()


def test_excel_sheet_and_header_configuration(client):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        pd.DataFrame({'a': [1]}).to_excel(writer, sheet_name='First', index=False)
        pd.DataFrame({'city': ['Paris', 'Tokyo'], 'value': [3, 4]}).to_excel(writer, sheet_name='Second', index=False)
    info, headers = upload(client, buffer.getvalue(), 'book.xlsx')
    assert info['inspection']['sheets'] == ['First', 'Second']
    base, _ = ingest(client, info, headers, sheet='Second')
    assert client.get(base + '/preview', headers=headers).json()['columns'] == ['city', 'value']
    info, headers = upload(client, b'alpha;1\nbeta;2\n', 'headerless.csv')
    base, _ = ingest(client, info, headers, header=None, delimiter=';')
    assert client.get(base + '/profile', headers=headers).json()['rows'] == 2


def test_expiry_cleanup_and_busy(client):
    info, headers = upload(client)
    base = '/api/v1/datasets/' + info['dataset_id']
    store = client.app.state.store
    with store.work():
        assert client.post(base + '/ingest', json={}, headers=headers).status_code == 429
    with store.db.connect() as db:
        db.execute('UPDATE datasets SET expires_at=0 WHERE id=?', (info['dataset_id'],))
    assert client.get(base, headers=headers).status_code == 410
    store.cleanup()
    assert not store.folder(info['dataset_id']).exists()


def test_ingest_failure_preserves_original(client):
    info, headers = upload(client)
    base = '/api/v1/datasets/' + info['dataset_id']
    result = client.post(base + '/ingest', json={'header': 100}, headers=headers)
    assert result.status_code == 202
    for _ in range(100):
        job = client.get(base + '/jobs/' + result.json()['job_id'], headers=headers).json()
        if job['status'] not in ('queued', 'running'):
            break
        time.sleep(.01)
    assert job['status'] == 'failed'
    assert client.get(base, headers=headers).json()['active_version'] is None
    assert client.app.state.store.original(info['dataset_id'])[0]


def test_upload_limits_and_filename_safety(client):
    info, headers = upload(client, filename='../../escape.csv')
    assert info['filename'] == 'escape.csv'
    assert not (client.app.state.store.root / 'escape.csv').exists()
    response = client.post('/api/v1/datasets/upload', content=b'x', headers={'Content-Length': str(100 * 1024 * 1024)})
    assert response.status_code == 413
    assert client.get('/static/../storage/metadata.sqlite3').status_code == 404


def test_public_limits():
    settings = Settings(_env_file=None, app_env='public', max_upload_mb=25, max_rows=100000)
    assert settings.limits['max_upload_bytes'] == 5 * 1024 * 1024
    assert settings.max_rows == 10000
