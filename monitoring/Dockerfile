FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

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
COPY maintenance ./maintenance
RUN python -m pip install --no-build-isolation --no-deps -e . \
    && mkdir -p /reports/drift \
    && chown -R lossguard:lossguard /app /home/lossguard /reports

USER 10001:10001

CMD ["python", "-m", "monitoring.scheduler"]
