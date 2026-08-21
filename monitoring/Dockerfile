FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src:/app

WORKDIR /app
COPY monitoring/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt
COPY src ./src
COPY ml ./ml
COPY monitoring ./monitoring

CMD ["python", "-m", "monitoring.scheduler"]
