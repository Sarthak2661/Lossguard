FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/lossguard

WORKDIR /app

RUN groupadd --gid 10001 lossguard \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin lossguard

COPY requirements/monitoring.lock /tmp/monitoring.lock
RUN python -m pip install --require-hashes --no-deps -r /tmp/monitoring.lock

COPY pyproject.toml README.md ./
COPY src ./src
COPY apps ./apps
COPY ml ./ml
COPY monitoring ./monitoring
RUN python -m pip install --no-build-isolation --no-deps -e . \
    && chown -R lossguard:lossguard /app /home/lossguard

USER 10001:10001

CMD ["python", "-m", "monitoring.scheduler"]
