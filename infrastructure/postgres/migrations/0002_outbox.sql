CREATE TABLE IF NOT EXISTS kafka_outbox (
    outbox_id BIGSERIAL PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    topic TEXT NOT NULL CHECK (topic IN ('txns.scored', 'txns.rejected')),
    message_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_at TIMESTAMPTZ,
    claim_token TEXT,
    published_at TIMESTAMPTZ,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_kafka_outbox_pending
    ON kafka_outbox (available_at, outbox_id) WHERE published_at IS NULL;
GRANT SELECT ON kafka_outbox TO grafana_reader;
