import asyncio
import logging
import math
import time
from collections import OrderedDict, deque
from contextlib import asynccontextmanager, suppress
from typing import Annotated

import pandas as pd
from fastapi import Depends, FastAPI, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from backend.config import ROOT, Settings
from backend.jobs import Jobs
from backend.models import (AnomalyRequest, ApplyRequest, DatasetResponse, DomainQualityRequest, EmptyRequest,
                            IngestRequest, JobCreated, JobResponse, PreviewRequest, ProfileResponse,
                            RestoreRequest, UploadResponse, VersionRequest)
from backend.store import Store, StoreError

logger = logging.getLogger('datalens')


def safe_scalar(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return str(value) if not math.isnan(value) else None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if hasattr(value, 'item'):
        return safe_scalar(value.item())
    return value


class BodyLimitMiddleware:
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        upload = scope.get('path') == '/api/v1/datasets/upload'
        maximum = self.limit + 65536 if upload else 65536
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            declared = maximum + 1
        if declared > maximum:
            response = JSONResponse({'error': {'code': 'too_large', 'message': 'Request exceeds size limit.'}}, 413)
            return await response(scope, receive, send)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message['type'] == 'http.request':
                total += len(message.get('body', b''))
                if total > maximum:
                    raise HTTPException(413, 'Request exceeds size limit.')
            return message

        await self.app(scope, limited_receive, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings)
    jobs = Jobs(store)

    @asynccontextmanager
    async def lifespan(app):
        async def cleanup():
            while True:
                await asyncio.sleep(60)
                if store.gate.acquire(blocking=False):
                    try:
                        await run_in_threadpool(store.cleanup)
                    finally:
                        store.gate.release()
        store.cleanup()
        task = asyncio.create_task(cleanup())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await run_in_threadpool(jobs.close)

    app = FastAPI(title='DataLens', version='1.0.0', lifespan=lifespan,
                  docs_url=None, redoc_url=None)
    app.state.store, app.state.jobs, app.state.settings = store, jobs, settings
    app.state.ai = None
    app.add_middleware(BodyLimitMiddleware, limit=settings.limits['max_upload_bytes'])
    clients: OrderedDict[str, deque] = OrderedDict()

    @app.middleware('http')
    async def security_headers(request: Request, call_next):
        if settings.app_env in {'public', 'cloud'} and request.url.path.startswith('/api/'):
            key = request.client.host if request.client else 'unknown'
            now = time.monotonic()
            if key not in clients:
                if len(clients) >= 1024:
                    clients.popitem(last=False)
                clients[key] = deque()
            timestamps = clients[key]
            while timestamps and timestamps[0] < now - 60:
                timestamps.popleft()
            if len(timestamps) >= 120:
                return JSONResponse({'error': {'code': 'rate_limit', 'message': 'Request limit reached. Retry in a minute.'}}, 429, headers={'Retry-After': '60'})
            timestamps.append(now)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api/') else 'no-cache'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        return JSONResponse({'error': {'code': exc.code, 'message': str(exc)}}, exc.status)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'error': {'code': 'invalid_data', 'message': str(exc)[:500]}}, 422)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Validation inputs can contain user data; never echo them in error payloads.
        return JSONResponse({'error': {'code': 'validation_error', 'message': 'Invalid request parameters. Check required fields and allowed values.'}}, 422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({'error': {'code': 'http_error', 'message': str(exc.detail)}}, exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error('request_failed method=%s type=%s', request.method, type(exc).__name__)
        return JSONResponse({'error': {'code': 'internal_error', 'message': 'Operation failed safely. Retry or consult server diagnostics.'}}, 500)

    def authorized(dataset_id: str, x_session_token: Annotated[str | None, Header()] = None):
        return store.authorize(dataset_id, x_session_token)

    Auth = Depends(authorized)
    prefix = '/api/v1'

    @app.get(prefix + '/health')
    def health():
        return {'status': 'ok', 'app_env': settings.app_env}

    @app.get(prefix + '/samples')
    def samples():
        return {'samples': [{'id': p.stem, 'name': p.stem.replace('_', ' ').title(),
                             'description': 'Synthetic demonstration data — safe to explore.'}
                            for p in sorted((ROOT / 'sample_datasets').glob('*')) if p.suffix in {'.csv', '.xlsx'}]}

    @app.post(prefix + '/datasets/upload', status_code=201, response_model=UploadResponse)
    async def upload(file: UploadFile):
        from backend.ingestion import inspect_file
        try:
            with store.work():
                data = await file.read(settings.limits['max_upload_bytes'] + 1)
                if len(data) > settings.limits['max_upload_bytes']:
                    raise StoreError('Upload exceeds configured limit.', 413, 'too_large')
                filename = (file.filename or 'upload.csv').replace('\\', '/').split('/')[-1][:200]
                inspection = await run_in_threadpool(inspect_file, data, filename, settings.limits)
                return await run_in_threadpool(store.create, data, filename, inspection)
        finally:
            await file.close()

    @app.post(prefix + '/datasets/sample/{sample_id}', status_code=201, response_model=UploadResponse)
    def sample(sample_id: str):
        from backend.ingestion import inspect_file
        candidates = {p.stem: p for p in (ROOT / 'sample_datasets').glob('*') if p.suffix in {'.csv', '.xlsx'}}
        if sample_id not in candidates:
            raise StoreError('Sample not found.', 404, 'not_found')
        with store.work():
            path = candidates[sample_id]
            data = path.read_bytes()
            return store.create(data, path.name, inspect_file(data, path.name, settings.limits))

    @app.get(prefix + '/datasets/{dataset_id}', response_model=DatasetResponse)
    def metadata(dataset_id: str, auth=Auth):
        return store.metadata(dataset_id)

    @app.post(prefix + '/datasets/{dataset_id}/ingest', status_code=202, response_model=JobCreated)
    def ingest(dataset_id: str, body: IngestRequest, auth=Auth):
        return {'job_id': jobs.submit_ingestion(dataset_id, body.model_dump())}

    @app.get(prefix + '/datasets/{dataset_id}/jobs/{job_id}', response_model=JobResponse)
    def job(dataset_id: str, job_id: str, auth=Auth):
        return jobs.get(dataset_id, job_id)

    @app.get(prefix + '/datasets/{dataset_id}/preview')
    def preview_rows(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), auth=Auth):
        with store.work():
            frame = store.frame(dataset_id)
            subset = frame.iloc[offset:offset + limit]
            return {'columns': list(frame.columns), 'rows': [{'row_id': int(index), 'values': [safe_scalar(v) for v in row]} for index, row in zip(subset.index, subset.itertuples(index=False, name=None))],
                    'total': len(frame), 'version': store.metadata(dataset_id)['active_version']}

    @app.get(prefix + '/datasets/{dataset_id}/profile', response_model=ProfileResponse)
    def profile(dataset_id: str, auth=Auth):
        with store.work():
            return store.analysis(dataset_id)[0]

    @app.get(prefix + '/datasets/{dataset_id}/columns/{column:path}')
    def column_profile(dataset_id: str, column: str, auth=Auth):
        with store.work():
            for item in store.analysis(dataset_id)[0]['column_profiles']:
                if item['name'] == column:
                    return item
        raise StoreError('Column not found.', 404, 'not_found')

    @app.get(prefix + '/datasets/{dataset_id}/quality')
    def quality(dataset_id: str, auth=Auth):
        with store.work():
            return {'issues': store.analysis(dataset_id)[1]}

    @app.post(prefix + '/datasets/{dataset_id}/quality')
    def domain_quality(dataset_id: str, body: DomainQualityRequest, auth=Auth):
        from backend.analysis import quality as analyze
        with store.work():
            rules = {column: rule.model_dump(exclude_none=True) for column, rule in body.domain_rules.items()}
            return {'issues': analyze(store.frame(dataset_id), rules)}

    @app.get(prefix + '/datasets/{dataset_id}/recommendations')
    def recommendations(dataset_id: str, auth=Auth):
        with store.work():
            return {'recommendations': store.analysis(dataset_id)[2]}

    @app.post(prefix + '/datasets/{dataset_id}/anomalies')
    def anomalies(dataset_id: str, body: AnomalyRequest, auth=Auth):
        from backend.analysis import anomalies as analyze
        with store.work():
            return analyze(store.frame(dataset_id), body.method, body.columns, body.threshold)

    @app.post(prefix + '/datasets/{dataset_id}/cleaning/preview')
    def preview_cleaning(dataset_id: str, body: PreviewRequest, auth=Auth):
        with store.work():
            return store.preview(dataset_id, body.operation.model_dump(), body.expected_version, body.expected_revision)

    @app.post(prefix + '/datasets/{dataset_id}/cleaning/apply', response_model=DatasetResponse)
    def apply_cleaning(dataset_id: str, body: ApplyRequest, auth=Auth):
        with store.work():
            return store.apply(dataset_id, body.preview_id, body.expected_version, body.expected_revision)

    def navigate(dataset_id, body, action, target=None):
        with store.work():
            return store.navigate(dataset_id, action, body.expected_version, body.expected_revision, target)

    @app.post(prefix + '/datasets/{dataset_id}/undo', response_model=DatasetResponse)
    def undo(dataset_id: str, body: VersionRequest, auth=Auth):
        return navigate(dataset_id, body, 'undo')

    @app.post(prefix + '/datasets/{dataset_id}/redo', response_model=DatasetResponse)
    def redo(dataset_id: str, body: VersionRequest, auth=Auth):
        return navigate(dataset_id, body, 'redo')

    @app.post(prefix + '/datasets/{dataset_id}/reset', response_model=DatasetResponse)
    def reset(dataset_id: str, body: VersionRequest, auth=Auth):
        return navigate(dataset_id, body, 'reset')

    @app.post(prefix + '/datasets/{dataset_id}/restore', response_model=DatasetResponse)
    def restore(dataset_id: str, body: RestoreRequest, auth=Auth):
        return navigate(dataset_id, body, 'restore', body.version)

    @app.get(prefix + '/datasets/{dataset_id}/history')
    def history(dataset_id: str, auth=Auth):
        return store.history(dataset_id)

    def attachment(result: tuple, name: str) -> Response:
        content, media, extension = result
        return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="datalens-{name}.{extension.lstrip(chr(46))}"'})

    @app.get(prefix + '/datasets/{dataset_id}/export')
    def export(dataset_id: str, format: str = Query('csv', pattern='^(csv|xlsx)$'), auth=Auth):
        from backend.exports import export_data
        with store.work():
            return attachment(export_data(store.frame(dataset_id), format), 'cleaned')

    @app.get(prefix + '/datasets/{dataset_id}/report')
    def report(dataset_id: str, format: str = Query('json', pattern='^(json|html)$'), auth=Auth):
        from backend.exports import report_data
        with store.work():
            summary, issues, _ = store.analysis(dataset_id)
            return attachment(report_data(summary, issues, store.history(dataset_id), format), 'report')

    @app.get(prefix + '/datasets/{dataset_id}/code')
    def code(dataset_id: str, language: str = Query('python', pattern='^(python|sql)$'), auth=Auth):
        from backend.exports import generate_code
        history = store.history(dataset_id)
        by_version = {v['version']: v for v in history['versions']}
        active, operations = history['active_version'], []
        while active is not None:
            version = by_version[active]
            if version['parent'] is not None:
                operations.append(version['operation'])
            active = version['parent']
        text = generate_code(list(reversed(operations)), language)
        return attachment((text.encode(), 'text/plain', 'py' if language == 'python' else 'sql'), 'reference')

    def gateway():
        if app.state.ai is None:
            from backend.ai import AIGateway
            app.state.ai = AIGateway(settings, store.db.path)
        return app.state.ai

    @app.get(prefix + '/ai/status')
    def ai_status():
        return gateway().status()

    @app.post(prefix + '/datasets/{dataset_id}/ai/explain')
    async def ai_explain(dataset_id: str, body: EmptyRequest, auth=Auth):
        with store.work():
            summary = (await run_in_threadpool(store.analysis, dataset_id))[0]
        return await gateway().explain(summary)

    @app.delete(prefix + '/datasets/{dataset_id}')
    def delete(dataset_id: str, auth=Auth):
        with store.work():
            store.delete(dataset_id)
        return {'deleted': True}

    frontend = ROOT / 'frontend'
    app.mount('/static', StaticFiles(directory=frontend), name='static')

    @app.get('/docs', include_in_schema=False)
    def api_docs():
        if settings.app_env in {'public', 'cloud'}:
            raise HTTPException(404, 'Not found.')
        path = frontend / 'api-docs.html'
        if not path.exists():
            raise HTTPException(503, 'API documentation assets are not available.')
        return FileResponse(path)

    @app.get('/', include_in_schema=False)
    def home():
        path = frontend / 'index.html'
        if not path.exists():
            raise HTTPException(503, 'Frontend assets have not been built.')
        return FileResponse(path)

    return app


app = create_app()
