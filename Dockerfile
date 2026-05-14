FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

FROM base AS watcher

RUN pip install --no-cache-dir requests==2.32.3

COPY watcher ./watcher

ENTRYPOINT ["python", "-m", "watcher.main"]

FROM base AS surya-service

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi==0.115.6 \
    "uvicorn[standard]==0.34.0" \
    surya-ocr==0.17.1 \
    requests==2.32.3 \
    "transformers>=4.56.1,<5.0.0"

COPY surya_service ./surya_service

EXPOSE 8077

CMD ["uvicorn", "surya_service.app:app", "--host", "0.0.0.0", "--port", "8077"]
