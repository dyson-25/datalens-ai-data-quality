import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from backend.store import Store, StoreError, encode


class Jobs:
    def __init__(self, store: Store):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='datalens')

    def submit_ingestion(self, dataset_id: str, options: dict) -> str:
        if not self.store.gate.acquire(blocking=False):
            raise StoreError('Processing slot occupied. Retry shortly.', 429, 'busy')
        try:
            if self.store.metadata(dataset_id)['active_version'] is not None:
                raise StoreError('Dataset already ingested.', 409, 'conflict')
            job_id = str(uuid4())
            with self.store.db.connect() as db:
                if db.execute('SELECT count(*) FROM jobs WHERE dataset_id=?', (dataset_id,)).fetchone()[0] >= 100:
                    raise StoreError('Ingestion attempt limit reached. Start a new session.', 429, 'capacity')
                db.execute('INSERT INTO jobs(id,dataset_id,status,created_at) VALUES(?,?,?,?)',
                           (job_id, dataset_id, 'queued', time.time()))
            try:
                self.executor.submit(self._ingest, dataset_id, job_id, options)
            except Exception:
                with self.store.db.connect() as db:
                    db.execute("UPDATE jobs SET status='failed',error=?,completed_at=? WHERE id=?",
                               ('Processing could not start. Retry ingestion.', time.time(), job_id))
                raise
            return job_id
        except Exception:
            self.store.gate.release()
            raise

    def _ingest(self, dataset_id: str, job_id: str, options: dict):
        status, error, result = 'failed', None, None
        try:
            from backend.ingestion import load_file
            with self.store.db.connect() as db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            deadline = time.monotonic() + self.store.settings.job_timeout_seconds
            data, filename = self.store.original(dataset_id)
            frame = load_file(data, filename, options, self.store.settings.limits)
            result = self.store.baseline(dataset_id, frame, deadline)
            status = 'succeeded'
        except TimeoutError:
            status, error = 'timed_out', 'Ingestion exceeded its time limit. No version was published.'
        except (ValueError, StoreError) as exc:
            error = str(exc)[:300]
        except Exception:
            error = 'Processing failed safely. Check file structure and retry.'
        finally:
            try:
                with self.store.db.connect() as db:
                    db.execute('UPDATE jobs SET status=?,error=?,result=?,completed_at=? WHERE id=?',
                               (status, error, encode(result) if result else None, time.time(), job_id))
            finally:
                self.store.gate.release()

    def get(self, dataset_id: str, job_id: str) -> dict:
        with self.store.db.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND dataset_id=?', (job_id, dataset_id)).fetchone()
        if not row:
            raise StoreError('Job not found.', 404, 'not_found')
        return {'job_id': row['id'], 'status': row['status'], 'error': row['error'],
                'result': json.loads(row['result']) if row['result'] else None}

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
