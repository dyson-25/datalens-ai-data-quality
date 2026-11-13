import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, filename TEXT NOT NULL,
 extension TEXT NOT NULL, inspection TEXT NOT NULL, created_at REAL NOT NULL,
 expires_at REAL NOT NULL, active_version INTEGER, revision INTEGER NOT NULL DEFAULT 0,
 redo TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS dataset_expiry ON datasets(expires_at);
CREATE TABLE IF NOT EXISTS versions (
 dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, parent INTEGER, operation TEXT NOT NULL,
 created_at REAL NOT NULL, PRIMARY KEY(dataset_id,version)
);
CREATE TABLE IF NOT EXISTS profiles (
 dataset_id TEXT NOT NULL, version INTEGER NOT NULL, profile TEXT NOT NULL,
 quality TEXT NOT NULL, recommendations TEXT NOT NULL,
 PRIMARY KEY(dataset_id,version),
 FOREIGN KEY(dataset_id,version) REFERENCES versions(dataset_id,version) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS previews (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
 version INTEGER NOT NULL, revision INTEGER NOT NULL, operation TEXT NOT NULL,
 expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS preview_dataset ON previews(dataset_id);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
 status TEXT NOT NULL, error TEXT, result TEXT, created_at REAL NOT NULL,
 completed_at REAL
);
CREATE INDEX IF NOT EXISTS job_dataset ON jobs(dataset_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            db.execute("UPDATE jobs SET status='failed',error='Server restarted; retry ingestion.' WHERE status IN ('queued','running')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()
