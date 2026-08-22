#!/usr/bin/env bash
set -euo pipefail

docker compose -f docker-compose.yml -f docker-compose.observability.yml \
  --profile observability up -d prometheus grafana

read_consumer_lag() {
  python - <<'PY'
import json
import urllib.parse
import urllib.request

query = 'redpanda_kafka_consumer_group_lag_sum{redpanda_group="lossguard-scorers"}'
url = "http://localhost:9090/api/v1/query?query=" + urllib.parse.quote(query)
with urllib.request.urlopen(url, timeout=5) as response:
    results = json.load(response)["data"]["result"]
print(float(results[0]["value"][1]) if results else 0)
PY
}

before=$(read_consumer_lag)
peak=$before
started_at=$(date +%s)

restart_consumer() {
  docker compose up -d consumer
}
trap restart_consumer EXIT

docker compose kill consumer
docker compose run --rm -e REPLAY_MODE=max -e REPLAY_LIMIT=2000 producer
while (( $(date +%s) - started_at < 60 )); do
  sleep 5
  current=$(read_consumer_lag)
  peak=$(python -c "print(max(float('$peak'), float('$current')))" )
done

restart_consumer
trap - EXIT

deadline=$(( $(date +%s) + 180 ))
after=$(read_consumer_lag)
while python -c "raise SystemExit(0 if float('$after') > 0 else 1)" && (( $(date +%s) < deadline )); do
  sleep 5
  after=$(read_consumer_lag)
done

python - <<PY
import json

result = {
    "lag_before": float("$before"),
    "lag_peak_while_consumer_stopped": float("$peak"),
    "lag_after_restart": float("$after"),
    "grafana_url": "http://localhost:3000/d/lossguard-pipeline/lossguard-pipeline-health",
}
print(json.dumps(result, indent=2))
if result["lag_peak_while_consumer_stopped"] <= result["lag_before"]:
    raise SystemExit("Observability acceptance failed: consumer lag did not increase.")
PY
