-- Upgrade volumes created by pre-migration LossGuard releases.
ALTER TABLE scored_transactions ADD COLUMN IF NOT EXISTS explanation_text TEXT;
ALTER TABLE scored_transactions ADD COLUMN IF NOT EXISTS explanation_source TEXT;
ALTER TABLE scored_transactions ADD COLUMN IF NOT EXISTS explanation_model TEXT;
ALTER TABLE scored_transactions ADD COLUMN IF NOT EXISTS explanation_generated_at TIMESTAMPTZ;
