FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1 \
	ECHOBIND_STORAGE_ROOT=/mnt/echobind-storage \
	VAULT_PATH=/mnt/echobind-storage/obsidian-vault

WORKDIR /app

COPY src/api/requirements.txt /app/requirements.txt

RUN pip install --upgrade pip \
	&& pip install -r /app/requirements.txt

COPY src/api /app/api
COPY src/common /app/common

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
	&& chown -R appuser:appuser /app

ENV PYTHONPATH=/app

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.app.server:app --host ${API_HOST:-0.0.0.0} --port ${API_PORT:-8000}"]
