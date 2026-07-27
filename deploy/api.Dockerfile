FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY apps ./apps
COPY database ./database
COPY packages ./packages
COPY scripts ./scripts

RUN mkdir -p /app/runtime/uploads \
    && addgroup --system raj \
    && adduser --system --ingroup raj raj \
    && chown -R raj:raj /app

USER raj

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
