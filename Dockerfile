FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/lossguard

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && groupadd --gid 10001 lossguard \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin lossguard \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/runtime.lock /tmp/runtime.lock
RUN python -m pip install --require-hashes --no-deps -r /tmp/runtime.lock

COPY pyproject.toml README.md ./
COPY src ./src
COPY apps ./apps
COPY ml ./ml
COPY monitoring ./monitoring
COPY streamlit_app.py ./streamlit_app.py
RUN python -m pip install --no-build-isolation --no-deps -e . \
    && chown -R lossguard:lossguard /app /home/lossguard

USER 10001:10001

CMD ["uvicorn", "apps.scoring_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
