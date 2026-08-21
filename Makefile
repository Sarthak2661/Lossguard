.PHONY: help copy-env up down logs topics train replay dbt test lint dashboard drift drift-shift

help:
	@echo "copy-env  Create .env from the safe local example"
	@echo "up        Start Redpanda, Postgres, scoring API, consumer, and dashboard"
	@echo "train     Train a bounded local model through Docker Compose"
	@echo "replay    Replay transactions (use LIMIT=10000 MODE=demo to override)"
	@echo "dbt       Build and test analytics marts"
	@echo "test      Run unit tests in Python 3.12"
	@echo "drift     Run one Evidently drift report"
	@echo "drift-shift  Run the in-memory distribution-shift acceptance demo"

copy-env:
	powershell -NoProfile -Command "if (-not (Test-Path .env)) { Copy-Item .env.example .env }"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

topics:
	docker compose run --rm topic-init

train:
	docker compose --profile tools run --rm trainer

replay:
	docker compose run --rm -e REPLAY_LIMIT=$(or $(LIMIT),10000) -e REPLAY_MODE=$(or $(MODE),demo) producer

dbt:
	docker compose --profile tools run --rm dbt build --profiles-dir .

test:
	docker compose --profile tools run --rm test

lint:
	docker compose --profile tools run --rm lint

dashboard:
	docker compose up -d dashboard

drift:
	docker compose run --rm drift-monitor python -m monitoring.drift_job

drift-shift:
	docker compose run --rm drift-monitor python -m monitoring.drift_job --simulate-shift
