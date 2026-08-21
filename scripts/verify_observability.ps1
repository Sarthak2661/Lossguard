$ErrorActionPreference = "Stop"

function Read-ConsumerLag {
    $query = [uri]::EscapeDataString('redpanda_kafka_consumer_group_lag_sum{redpanda_group="lossguard-scorers"}')
    $response = Invoke-RestMethod -Uri "http://localhost:9090/api/v1/query?query=$query"
    if (-not $response.data.result) { return 0 }
    return [double]$response.data.result[0].value[1]
}

$before = Read-ConsumerLag
$peak = $before
$startedAt = Get-Date

try {
    docker compose kill consumer
    docker compose run --rm -e REPLAY_MODE=max -e REPLAY_LIMIT=2000 producer
    while (((Get-Date) - $startedAt).TotalSeconds -lt 60) {
        Start-Sleep -Seconds 5
        $peak = [math]::Max($peak, (Read-ConsumerLag))
    }
}
finally {
    docker compose up -d consumer
}

$deadline = (Get-Date).AddMinutes(3)
$after = Read-ConsumerLag
while ($after -gt 0 -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $after = Read-ConsumerLag
}

[pscustomobject]@{
    lag_before = $before
    lag_peak_while_consumer_stopped = $peak
    lag_after_restart = $after
    grafana_url = "http://localhost:3000/d/lossguard-pipeline/lossguard-pipeline-health"
}

if ($peak -le $before) {
    throw "Observability acceptance failed: consumer lag did not increase."
}
