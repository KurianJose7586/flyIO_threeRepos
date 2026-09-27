-- PostgreSQL DDL initialization script for FlyIO cross-service request event tracking.
--
-- request_id is the cross-service correlation key (see app/middlewares/request_id.py
-- and FlyIO_Project_Context.md section 4). By convention it carries Admin's
-- `jobs.id` UUID when a request originates from a scrape/store job, so this table's
-- rows can be joined against Admin's `job_events` table on that shared value.
--
-- service identifies which of the three FlyIO microservices wrote a given row. All
-- three services are expected to write to one shared physical database, so this
-- column is required to answer "where exactly did this request fail?" per-service.

CREATE TABLE IF NOT EXISTS request_events (
    id BIGSERIAL PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm',
    event_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'info',
    message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Idempotent for a table already created by an older version of this script (before
-- the `service` column existed) or by another service's own migration.
ALTER TABLE request_events ADD COLUMN IF NOT EXISTS service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm';

CREATE INDEX IF NOT EXISTS idx_request_events_request_id ON request_events(request_id);
CREATE INDEX IF NOT EXISTS idx_request_events_event_type ON request_events(event_type);
CREATE INDEX IF NOT EXISTS idx_request_events_request_id_service ON request_events(request_id, service);
