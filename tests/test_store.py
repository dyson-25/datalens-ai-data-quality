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


@pytest.mark.parametrize('status', ['queued', 'running'])
def test_restart_marks_unfinished_jobs_failed(store, status):
    info, _ = dataset(store)
    with store.db.connect() as db:
        db.execute('INSERT INTO jobs(id,dataset_id,status,created_at) VALUES(?,?,?,?)', ('pending', info['dataset_id'], status, time.time()))
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


def test_storage_transaction_failure_rolls_back_snapshot_and_preserves_preview(store):
    import sqlite3
    info = store.create(b'a\n A \n', 'synthetic.csv', {'format': 'csv'})
    frame = pd.DataFrame({'a': [' A ']}, index=pd.Index([0], name='__row_id__'))
    meta = store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    pending = store.preview(info['dataset_id'], {'kind': 'trim', 'column': 'a'}, 0, meta['revision'])
    baseline = store.snapshot_path(info['dataset_id'], 0).read_bytes()
    with store.db.connect() as db:
        db.execute("CREATE TRIGGER fail_new_version BEFORE INSERT ON versions WHEN NEW.version>0 "
                   "BEGIN SELECT RAISE(ABORT,'synthetic metadata failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='synthetic metadata failure'):
        store.apply(info['dataset_id'], pending['preview_id'], 0, meta['revision'])
    assert store.metadata(info['dataset_id']) == meta
    assert not store.snapshot_path(info['dataset_id'], 1).exists()
    assert store.snapshot_path(info['dataset_id'], 0).read_bytes() == baseline
    with store.db.connect() as db:
        assert db.execute('SELECT count(*) FROM previews').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM versions').fetchone()[0] == 1
        db.execute('DROP TRIGGER fail_new_version')
    assert store.apply(info['dataset_id'], pending['preview_id'], 0, meta['revision'])['active_version'] == 1


def test_version_capacity_failure_never_publishes(store):
    info = store.create(b'a\n A \n', 'synthetic.csv', {'format': 'csv'})
    frame = pd.DataFrame({'a': [' A ']}, index=pd.Index([0], name='__row_id__'))
    meta = store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    first = store.preview(info['dataset_id'], {'kind': 'trim', 'column': 'a'}, 0, meta['revision'])
    changed = store.apply(info['dataset_id'], first['preview_id'], 0, meta['revision'])
    store.settings.max_versions = 2
    next_preview = store.preview(info['dataset_id'], {'kind': 'case', 'column': 'a', 'params': {'mode': 'lower'}},
                                 1, changed['revision'])
    with pytest.raises(StoreError, match='Version limit'):
        store.apply(info['dataset_id'], next_preview['preview_id'], 1, changed['revision'])
    assert store.metadata(info['dataset_id']) == changed
    assert not store.snapshot_path(info['dataset_id'], 2).exists()


def test_baseline_rechecks_actual_session_expiry_before_publication(store):
    info, frame = dataset(store)
    with store.db.connect() as db:
        db.execute('UPDATE datasets SET expires_at=0 WHERE id=?', (info['dataset_id'],))
    with pytest.raises(StoreError, match='expired during ingestion'):
        store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    assert store.metadata(info['dataset_id'])['active_version'] is None
    assert store.history(info['dataset_id'])['versions'] == []
    assert not store.snapshot_path(info['dataset_id'], 0).exists()
    store.cleanup()
    assert not store.folder(info['dataset_id']).exists()


@pytest.mark.parametrize('invalid', ['duplicate_columns', 'duplicate_rows', 'row_limit', 'column_limit', 'memory_limit'])
def test_invalid_snapshot_invariants_never_publish(store, invalid):
    info, frame = dataset(store)
    if invalid == 'duplicate_columns':
        frame = pd.DataFrame([[1, 2]], columns=['a', 'a'], index=pd.Index([0], name='__row_id__'))
    elif invalid == 'duplicate_rows':
        frame = pd.DataFrame({'a': [1, 2]}, index=pd.Index([0, 0], name='__row_id__'))
    elif invalid == 'row_limit':
        store.settings.max_rows = 1
        frame = pd.DataFrame({'a': [1, 2]}, index=pd.Index([0, 1], name='__row_id__'))
    elif invalid == 'column_limit':
        store.settings.max_columns = 1
        frame['b'] = 2
    else:
        # Public mode permits 30 MiB uncompressed; one repeated synthetic scalar stays local.
        store.settings.app_env = 'public'
        frame['a'] = ['x' * (31 * 1024 * 1024)]
    with pytest.raises(StoreError):
        store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    assert store.metadata(info['dataset_id'])['active_version'] is None
    assert not store.snapshot_path(info['dataset_id'], 0).exists()


def test_snapshot_cannot_overwrite_committed_version(store):
    info, frame = dataset(store)
    store.baseline(info['dataset_id'], frame, time.monotonic() + 10)
    path = store.snapshot_path(info['dataset_id'], 0)
    before = path.read_bytes()
    frame.loc[0, 'a'] = 9
    with pytest.raises(StoreError, match='already exists'):
        store.write_snapshot(info['dataset_id'], 0, frame)
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o222 == 0
    original_path = store.folder(info['dataset_id']) / 'original' / 'source.csv'
    assert original_path.stat().st_mode & 0o222 == 0


def test_recovery_removes_orphan_session_and_preserves_non_session_directories(store):
    from uuid import uuid4
    orphan = store.sessions / str(uuid4())
    orphan.mkdir()
    (orphan / 'partial').write_bytes(b'interrupted synthetic write')
    unrelated = store.sessions / 'not-a-session'
    unrelated.mkdir()
    (unrelated / 'keep').write_bytes(b'keep')
    Store(store.settings)
    assert not orphan.exists()
    assert (unrelated / 'keep').read_bytes() == b'keep'
