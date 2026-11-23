FROM node:22-slim AS frontend
RUN apt-get update && apt-get install -y --no-install-recommends unzip && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY hosting/deployment-source.part*.b64 /tmp/
RUN cat /tmp/deployment-source.part*.b64 | tr -d '\r\n' > /tmp/source.b64 && base64 -d /tmp/source.b64 > /tmp/source.zip && unzip -q /tmp/source.zip -d /build && cd /build/final-bank-inteligence-system/frontend && npm ci && npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-mar && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY hosting/deployment-source.part*.b64 /tmp/
RUN cat /tmp/deployment-source.part*.b64 | tr -d '\r\n' > /tmp/source.b64 && base64 -d /tmp/source.b64 > /tmp/source.zip && unzip -q /tmp/source.zip -d /tmp/unpacked && cp -a /tmp/unpacked/final-bank-inteligence-system/backend/. /app/
COPY --from=frontend /build/final-bank-inteligence-system/frontend/dist /app/frontend_dist
ENV FRONTEND_DIST=/app/frontend_dist DB_PATH=/data/statements.db PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OCR_LANG=eng+hin+mar
RUN useradd --system --uid 10001 --create-home appuser && mkdir -p /data && chown -R appuser:appuser /app /data
EXPOSE 8000
CMD ["sh", "-c", "chown appuser:appuser /data && exec su -s /bin/sh appuser -c 'uvicorn statement_analyser.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*'"]
