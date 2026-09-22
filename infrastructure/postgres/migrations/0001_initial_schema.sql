CREATE TABLE IF NOT EXISTS scored_transactions (
    transaction_id TEXT PRIMARY KEY, event_time TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), customer_id TEXT NOT NULL,
    merchant TEXT NOT NULL, merchant_category TEXT NOT NULL, channel TEXT NOT NULL,
    amount NUMERIC(14, 2) NOT NULL, order_margin_pct NUMERIC(6, 4) NOT NULL,
    customer_ltv_band TEXT NOT NULL, fraud_label BOOLEAN,
    fraud_probability NUMERIC(10, 8) NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approve', 'verify', 'decline')),
    verify_threshold NUMERIC(10, 8) NOT NULL, decline_threshold NUMERIC(10, 8) NOT NULL,
    expected_cost_approve NUMERIC(14, 4) NOT NULL,
    expected_cost_verify NUMERIC(14, 4) NOT NULL,
    expected_cost_decline NUMERIC(14, 4) NOT NULL,
    realized_policy_cost NUMERIC(14, 4), baseline_cost NUMERIC(14, 4),
    estimated_savings NUMERIC(14, 4), model_version TEXT NOT NULL,
    explanation JSONB NOT NULL DEFAULT '[]'::jsonb,
    feature_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    explanation_text TEXT, explanation_source TEXT, explanation_model TEXT,
    explanation_generated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scored_event_time ON scored_transactions (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_scored_category ON scored_transactions (merchant_category);
CREATE INDEX IF NOT EXISTS idx_scored_decision ON scored_transactions (decision);

CREATE TABLE IF NOT EXISTS rejected_transactions (
    rejection_id BIGSERIAL PRIMARY KEY, rejected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_topic TEXT NOT NULL, error_type TEXT NOT NULL, error_message TEXT NOT NULL,
    transaction_id TEXT, payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rejected_at ON rejected_transactions (rejected_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_metrics (
    metric_time TIMESTAMPTZ NOT NULL DEFAULT NOW(), metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL, labels JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_pipeline_metrics_time_name
    ON pipeline_metrics (metric_time DESC, metric_name);

CREATE TABLE IF NOT EXISTS model_drift_reports (
    report_id BIGSERIAL PRIMARY KEY, generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_version TEXT NOT NULL, reference_rows INTEGER NOT NULL, current_rows INTEGER NOT NULL,
    drifted_features INTEGER NOT NULL, total_features INTEGER NOT NULL,
    drift_share DOUBLE PRECISION NOT NULL, drift_threshold DOUBLE PRECISION NOT NULL,
    health_status TEXT NOT NULL
        CHECK (health_status IN ('ok', 'drifting', 'insufficient_data', 'error')),
    current_window_start TIMESTAMPTZ, current_window_end TIMESTAMPTZ,
    report_json_path TEXT, report_html_path TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_model_drift_reports_generated
    ON model_drift_reports (generated_at DESC);

SELECT format('CREATE ROLE grafana_reader LOGIN PASSWORD %L', :'grafana_reader_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_reader')
\gexec
ALTER ROLE grafana_reader PASSWORD :'grafana_reader_password';
DO $$ BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO grafana_reader', current_database());
END $$;
CREATE SCHEMA IF NOT EXISTS analytics_marts;
GRANT USAGE ON SCHEMA public, analytics_marts TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public, analytics_marts TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics_marts GRANT SELECT ON TABLES TO grafana_reader;
