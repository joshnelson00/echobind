FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ECHOBIND_STORAGE_ROOT=/mnt/echobind-storage \
    VAULT_PATH=/mnt/echobind-storage/obsidian-vault

WORKDIR /app/src

COPY src/worker/requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

COPY src/common /app/src/common
COPY src/worker /app/src/worker

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app/src

ENV PYTHONPATH=/app/src

USER appuser

CMD ["python", "-m", "worker.main"]
