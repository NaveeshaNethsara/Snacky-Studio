FROM node:24-bookworm-slim AS ui
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SNACKY_DOWNLOADS_DIR=/work SNACKY_DATA_DIR=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=ui /usr/local/bin/node /usr/local/bin/node
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-cloud.txt
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY scripts/init_bucket.py ./scripts/init_bucket.py
COPY --from=ui /build/app/web ./app/web
# Bundle the static FFmpeg binaries while building, rather than on each worker boot.
RUN python -c "import static_ffmpeg; static_ffmpeg.add_paths()"
RUN groupadd -r snacky && useradd -r -g snacky -d /data snacky && mkdir -p /work /data && chown snacky:snacky /work /data
USER snacky
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
