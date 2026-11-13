FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY tailwind.config.js ./
COPY frontend/ ./frontend/
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    APP_ENV=public \
    AI_ENABLED=false \
    AI_ZERO_COST_MODE=true \
    STORAGE_ROOT=/app/storage \
    TMPDIR=/app/storage/tmp \
    PORT=8000
WORKDIR /app
COPY requirements.lock.txt ./requirements.lock.txt
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && groupadd --gid 10001 datalens \
    && useradd --uid 10001 --gid datalens --no-create-home --shell /usr/sbin/nologin datalens \
    && mkdir -p /app/storage/tmp \
    && chown -R datalens:datalens /app/storage \
    && chmod 700 /app/storage /app/storage/tmp
COPY backend/ ./backend/
COPY sample_datasets/ ./sample_datasets/
COPY --from=frontend-build /build/frontend/index.html /build/frontend/app.js /build/frontend/api.js /build/frontend/charts.js /build/frontend/ui.js /build/frontend/styles.css ./frontend/
COPY --from=frontend-build /build/frontend/api-docs.html /build/frontend/api-docs.js ./frontend/
COPY --from=frontend-build /build/frontend/vendor/ ./frontend/vendor/
USER datalens:datalens
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1"]
