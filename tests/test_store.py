import time

import pandas as pd
import pytest

from backend.config import Settings
from backend.store import Store, StoreError


@pytest.fixture
def store(tmp_path):
    return Store(Settings(_env_file=None, app_env='test', storage_root=tmp_path, ai_enabled=False))


def dataset(store):
    info = store.create(b'a\n1\n', 'sample.csv', {'format': 'csv'})
    frame = pd.DataFrame({'a': [1]}, index=pd.Index([0], name='__row_id__'))
    return info, frame


def test_atomic_baseline_and_expired_job(store):
    info, frame = dataset(store)
    with pytest.raises(TimeoutError):
        store.baseline(info['dataset_id'], frame, time.monotonic() - 1)
    assert store.metadata(info['dataset_id'])['active_version'] is None
    assert not store.snapshot_path(info['dataset_id'], 0).exists()
    meta = store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    assert meta['active_version'] == 0
    pd.testing.assert_frame_equal(store.frame(info['dataset_id']), frame)
    with pytest.raises(StoreError):
        store.baseline(info['dataset_id'], frame, time.monotonic() + 10)


def test_no_row_identity_loss(store):
    info, frame = dataset(store)
    frame.index.name = None
    with pytest.raises(StoreError, match='identifiers'):
        store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    assert not store.snapshot_path(info['dataset_id'], 0).exists()


def test_authorization_and_storage_paths(store):
    info, _ = dataset(store)
    assert store.authorize(info['dataset_id'], info['token'])['id'] == info['dataset_id']
    for candidate in (None, 'wrong', info['dataset_id']):
        with pytest.raises(StoreError):
            store.authorize(info['dataset_id'], candidate)
    for candidate in ('../../other', '/etc/passwd', 'invalid'):
        with pytest.raises(StoreError):
            store.folder(candidate)
    with store.db.connect() as db:
        saved = db.execute('SELECT token_hash FROM datasets').fetchone()[0]
    assert saved != info['token']


def test_restart_marks_unfinished_jobs_failed(store):
    info, _ = dataset(store)
    with store.db.connect() as db:
        db.execute('INSERT INTO jobs(id,dataset_id,status,created_at) VALUES(?,?,?,?)', ('pending', info['dataset_id'], 'running', time.time()))
    restarted = Store(store.settings)
    with restarted.db.connect() as db:
        row = db.execute('SELECT status,error FROM jobs WHERE id=?', ('pending',)).fetchone()
    assert row['status'] == 'failed'
    assert 'restarted' in row['error']


def test_crash_recovers_only_unpublished_snapshots(store):
    info, frame = dataset(store)
    store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    committed = store.snapshot_path(info['dataset_id'], 0)
    original = committed.read_bytes()
    orphan = store.write_snapshot(info['dataset_id'], 1, frame)
    pending = orphan.with_suffix('.pending')
    pending.write_bytes(b'interrupted')
    Store(store.settings)
    assert committed.read_bytes() == original
    assert not orphan.exists()
    assert not pending.exists()


def test_semaphore_and_session_capacity(store):
    with store.work():
        with pytest.raises(StoreError, match='running'):
            with store.work():
                pytest.fail('Should reject concurrent work')
    store.settings.max_sessions = 1
    dataset(store)
    with pytest.raises(StoreError, match='Session limit'):
        dataset(store)
