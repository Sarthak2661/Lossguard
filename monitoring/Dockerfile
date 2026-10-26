FROM python:3.15.0-slim-bookworm@sha256:0e019bbdfb5d9874cb2389f1c2884b64aa2ac97c99960b5bc521cef978c0617d

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
