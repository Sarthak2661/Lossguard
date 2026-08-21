FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY apps ./apps
COPY ml ./ml
COPY analytics ./analytics
COPY tests ./tests

RUN pip install --upgrade pip && pip install ".[dev,dbt]"

CMD ["python", "-m", "apps.scoring_api.main"]
