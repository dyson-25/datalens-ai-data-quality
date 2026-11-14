import hashlib
import json
import os
import secrets
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pandas as pd

from backend.config import Settings
from backend.database import Database


class StoreError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = 'invalid_request'):
        super().__init__(message)
        self.status = status
        self.code = code


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.storage_root.resolve()
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = Database(self.root / 'metadata.sqlite3')
        self.gate = threading.BoundedSemaphore(1)
        self.recover_snapshots()

    def recover_snapshots(self):
        # Atomic rename may finish before the metadata transaction on a crash.
        with self.db.connect() as db:
            rows = db.execute('SELECT id FROM datasets').fetchall()
            versions = {(r['dataset_id'], r['version']) for r in db.execute('SELECT dataset_id,version FROM versions')}
        known = {row['id'] for row in rows}
        for folder in self.sessions.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            try:
                if str(UUID(folder.name)) != folder.name:
                    continue
            except ValueError:
                continue
            if folder.name not in known:
                shutil.rmtree(folder)
                continue
            snapshots = folder / 'snapshots'
            if not snapshots.is_dir() or snapshots.is_symlink():
                continue
            for path in snapshots.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                if path.suffix == '.pending':
                    path.unlink()
                elif path.suffix == '.parquet' and path.stem.startswith('v') and path.stem[1:].isdigit():
                    if (folder.name, int(path.stem[1:])) not in versions:
                        path.unlink()

    @contextmanager
    def work(self):
        if not self.gate.acquire(blocking=False):
            raise StoreError('Another operation is running. Retry shortly.', 429, 'busy')
        try:
            yield
        finally:
            self.gate.release()

    def folder(self, dataset_id: str) -> Path:
        try:
            canonical = str(UUID(dataset_id))
        except (ValueError, AttributeError):
            raise StoreError('Dataset not found.', 404, 'not_found') from None
        if canonical != dataset_id:
            raise StoreError('Dataset not found.', 404, 'not_found')
        path = self.sessions / canonical
        if path.is_symlink() or not path.resolve().is_relative_to(self.sessions):
            raise StoreError('Invalid storage path.')
        return path

    def authorize(self, dataset_id: str, token: str | None) -> dict:
        self.folder(dataset_id)
        with self.db.connect() as db:
            row = db.execute('SELECT * FROM datasets WHERE id=?', (dataset_id,)).fetchone()
        candidate = hashlib.sha256((token or '')[:512].encode()).hexdigest()
        if not row or not secrets.compare_digest(candidate, row['token_hash']):
            raise StoreError('Dataset not found or access token invalid.', 404, 'not_found')
        if row['expires_at'] <= time.time():
            raise StoreError('Session expired. Upload the source again.', 410, 'expired')
        return dict(row)

    def metadata(self, dataset_id: str) -> dict:
        with self.db.connect() as db:
            row = db.execute('SELECT * FROM datasets WHERE id=?', (dataset_id,)).fetchone()
        if not row:
            raise StoreError('Dataset not found.', 404, 'not_found')
        return {'dataset_id': row['id'], 'filename': row['filename'],
                'active_version': row['active_version'], 'revision': row['revision'],
                'created_at': row['created_at'], 'expires_at': row['expires_at']}

    def check_capacity(self, additional: int = 0):
        size = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file() and not p.is_symlink())
        if size + additional > self.settings.max_storage_mb * 1024 * 1024:
            raise StoreError('Temporary storage is full. Delete a session or wait for cleanup.', 413, 'capacity')

    def create(self, data: bytes, filename: str, inspection: dict) -> dict:
        self.cleanup()
        self.check_capacity(len(data))
        with self.db.connect() as db:
            count = db.execute('SELECT count(*) FROM datasets').fetchone()[0]
        if count >= self.settings.max_sessions:
            raise StoreError('Session limit reached. Delete a session or wait for expiry.', 429, 'capacity')
        dataset_id, token = str(uuid4()), secrets.token_urlsafe(32)
        extension = Path(filename).suffix.lower()
        folder = self.folder(dataset_id)
        for name in ('original', 'snapshots', 'reports'):
            (folder / name).mkdir(parents=True, mode=0o700)
        try:
            original = folder / 'original' / ('source' + extension)
            with original.open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            original.chmod(0o400)
            now = time.time()
            with self.db.connect() as db:
                db.execute('INSERT INTO datasets(id,token_hash,filename,extension,inspection,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',
                           (dataset_id, hashlib.sha256(token.encode()).hexdigest(), filename[:200], extension,
                            encode(inspection), now, now + self.settings.session_ttl_minutes * 60))
        except Exception:
            shutil.rmtree(folder)
            raise
        return {**self.metadata(dataset_id), 'token': token, 'inspection': inspection}

    def original(self, dataset_id: str) -> tuple[bytes, str]:
        with self.db.connect() as db:
            row = db.execute('SELECT filename,extension FROM datasets WHERE id=?', (dataset_id,)).fetchone()
        return (self.folder(dataset_id) / 'original' / ('source' + row['extension'])).read_bytes(), row['filename']

    def snapshot_path(self, dataset_id: str, version: int) -> Path:
        return self.folder(dataset_id) / 'snapshots' / f'v{version}.parquet'

    def frame(self, dataset_id: str, version: int | None = None) -> pd.DataFrame:
        if version is None:
            version = self.metadata(dataset_id)['active_version']
        if version is None:
            raise StoreError('Ingest the dataset first.', 409, 'not_ingested')
        path = self.snapshot_path(dataset_id, version)
        if not path.is_file():
            raise StoreError('Snapshot unavailable.', 404, 'not_found')
        return pd.read_parquet(path)

    def validate_frame(self, frame: pd.DataFrame):
        if len(frame) > self.settings.max_rows or len(frame.columns) > self.settings.max_columns:
            raise StoreError('Dataset exceeds configured row or column limits.', 413, 'capacity')
        if not frame.columns.is_unique or not frame.index.is_unique:
            raise StoreError('Column labels and internal row identifiers must be unique.')
        if frame.index.name != '__row_id__':
            raise StoreError('Internal row identifiers are missing.')
        if int(frame.memory_usage(deep=True).sum()) > self.settings.limits['max_uncompressed_bytes']:
            raise StoreError('Dataset memory estimate exceeds the configured processing limit.', 413, 'capacity')

    def write_snapshot(self, dataset_id: str, version: int, frame: pd.DataFrame) -> Path:
        self.validate_frame(frame)
        path = self.snapshot_path(dataset_id, version)
        temporary = path.with_suffix('.pending')
        if path.exists():
            raise StoreError('Snapshot version already exists.', 409, 'conflict')
        try:
            frame.to_parquet(temporary, index=True)
            self.check_capacity()
            with temporary.open('rb') as source:
                os.fsync(source.fileno())
            os.replace(temporary, path)
            path.chmod(0o400)
            return path
        finally:
            temporary.unlink(missing_ok=True)

    def baseline(self, dataset_id: str, frame: pd.DataFrame, deadline: float):
        if self.metadata(dataset_id)['active_version'] is not None:
            raise StoreError('Dataset has already been ingested.', 409, 'conflict')
        path = self.write_snapshot(dataset_id, 0, frame)
        try:
            if time.monotonic() > deadline:
                raise TimeoutError('Ingestion timed out. No snapshot was published.')
            with self.db.connect() as db:
                row = db.execute('SELECT expires_at FROM datasets WHERE id=?', (dataset_id,)).fetchone()
                if not row or row['expires_at'] <= time.time():
                    raise StoreError('Session expired during ingestion.', 410, 'expired')
                db.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (dataset_id, 0, None, encode({'kind': 'original'}), time.time()))
                db.execute('UPDATE datasets SET active_version=0,revision=revision+1 WHERE id=?', (dataset_id,))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.metadata(dataset_id)

    def check_version(self, dataset_id: str, version: int, revision: int) -> dict:
        meta = self.metadata(dataset_id)
        if meta['expires_at'] <= time.time():
            raise StoreError('Session expired.', 410, 'expired')
        if meta['active_version'] != version or meta['revision'] != revision:
            raise StoreError('Dataset changed. Refresh and preview again.', 409, 'stale_version')
        return meta

    def analysis(self, dataset_id: str) -> tuple[dict, list, list]:
        from backend.analysis import profile, quality, recommendations
        version = self.metadata(dataset_id)['active_version']
        with self.db.connect() as db:
            row = db.execute('SELECT * FROM profiles WHERE dataset_id=? AND version=?', (dataset_id, version)).fetchone()
        if row:
            return tuple(json.loads(row[key]) for key in ('profile', 'quality', 'recommendations'))
        frame = self.frame(dataset_id)
        result = profile(frame), quality(frame), recommendations(frame)
        with self.db.connect() as db:
            db.execute('INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?)', (dataset_id, version, *(encode(part) for part in result)))
        return result

    def preview(self, dataset_id: str, operation: dict, version: int, revision: int) -> dict:
        from backend.cleaning import preview_operation
        self.check_version(dataset_id, version, revision)
        result = preview_operation(self.frame(dataset_id), operation)
        preview_id = str(uuid4())
        with self.db.connect() as db:
            db.execute('DELETE FROM previews WHERE dataset_id=?', (dataset_id,))
            db.execute('INSERT INTO previews VALUES(?,?,?,?,?,?)', (preview_id, dataset_id, version, revision, encode(operation), time.time() + 600))
        return {**result, 'preview_id': preview_id, 'version': version, 'operation': operation}

    def apply(self, dataset_id: str, preview_id: str, version: int, revision: int) -> dict:
        from backend.cleaning import apply_operation
        self.check_version(dataset_id, version, revision)
        with self.db.connect() as db:
            preview = db.execute('SELECT * FROM previews WHERE id=? AND dataset_id=?', (preview_id, dataset_id)).fetchone()
            maximum = db.execute('SELECT max(version),count(*) FROM versions WHERE dataset_id=?', (dataset_id,)).fetchone()
        if not preview or preview['expires_at'] <= time.time() or preview['version'] != version or preview['revision'] != revision:
            raise StoreError('Preview expired or stale. Preview the operation again.', 409, 'stale_preview')
        if maximum[1] >= self.settings.max_versions:
            raise StoreError('Version limit reached. Export and start a new session.', 413, 'capacity')
        operation = json.loads(preview['operation'])
        transformed = apply_operation(self.frame(dataset_id), operation)
        new_version = maximum[0] + 1
        path = self.write_snapshot(dataset_id, new_version, transformed)
        try:
            self.check_version(dataset_id, version, revision)
            with self.db.connect() as db:
                db.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (dataset_id, new_version, version, encode(operation), time.time()))
                db.execute("UPDATE datasets SET active_version=?,revision=revision+1,redo='[]' WHERE id=?", (new_version, dataset_id))
                db.execute('DELETE FROM previews WHERE dataset_id=?', (dataset_id,))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.metadata(dataset_id)

    def history(self, dataset_id: str) -> dict:
        with self.db.connect() as db:
            versions = db.execute('SELECT version,parent,operation,created_at FROM versions WHERE dataset_id=? ORDER BY version', (dataset_id,)).fetchall()
        meta = self.metadata(dataset_id)
        return {'active_version': meta['active_version'], 'revision': meta['revision'],
                'versions': [{**dict(row), 'operation': json.loads(row['operation'])} for row in versions]}

    def navigate(self, dataset_id: str, action: str, version: int, revision: int, target: int | None = None) -> dict:
        self.check_version(dataset_id, version, revision)
        with self.db.connect() as db:
            row = db.execute('SELECT redo FROM datasets WHERE id=?', (dataset_id,)).fetchone()
            redo = json.loads(row['redo'])
            if action == 'undo':
                parent = db.execute('SELECT parent FROM versions WHERE dataset_id=? AND version=?', (dataset_id, version)).fetchone()
                if not parent or parent['parent'] is None:
                    raise StoreError('Already at the original version.', 409, 'no_undo')
                target = parent['parent']
                redo.append(version)
            elif action == 'redo':
                if not redo:
                    raise StoreError('No version to redo.', 409, 'no_redo')
                target = redo.pop()
            else:
                target = 0 if action == 'reset' else target
                redo = []
            if not db.execute('SELECT 1 FROM versions WHERE dataset_id=? AND version=?', (dataset_id, target)).fetchone():
                raise StoreError('Version not found.', 404, 'not_found')
            db.execute('UPDATE datasets SET active_version=?,revision=revision+1,redo=? WHERE id=?', (target, encode(redo), dataset_id))
            db.execute('DELETE FROM previews WHERE dataset_id=?', (dataset_id,))
        return self.metadata(dataset_id)

    def delete(self, dataset_id: str):
        folder = self.folder(dataset_id)
        with self.db.connect() as db:
            db.execute('DELETE FROM datasets WHERE id=?', (dataset_id,))
        if folder.exists():
            shutil.rmtree(folder)

    def cleanup(self):
        with self.db.connect() as db:
            rows = db.execute('SELECT id FROM datasets WHERE expires_at<=?', (time.time(),)).fetchall()
            db.execute('DELETE FROM previews WHERE expires_at<=?', (time.time(),))
        for row in rows:
            self.delete(row['id'])
