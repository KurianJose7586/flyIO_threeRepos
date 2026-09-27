import { query } from "../db/pgPool";

/**
 * Migration 007: prompt_history & request_events tables for cross-service LLM tracking.
 *
 * prompt_history — stores user prompts, LLM plan responses, and generation status.
 * request_events — stores lifecycle event logs keyed by shared request_id for cross-service tracing.
 */
export async function runMigration007(): Promise<void> {
  console.log("[DB] Running migration 007 — prompt_history, request_events...");

  await query(`
    CREATE TABLE IF NOT EXISTS prompt_history (
      id            BIGSERIAL PRIMARY KEY,
      request_id    TEXT NOT NULL UNIQUE,
      prompt_text   TEXT NOT NULL,
      response_data JSONB,
      status        TEXT NOT NULL DEFAULT 'pending',
      metadata      JSONB DEFAULT '{}'::jsonb,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_prompt_history_request_id
    ON prompt_history(request_id)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_prompt_history_status
    ON prompt_history(status)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_prompt_history_created_at
    ON prompt_history(created_at DESC)
  `);

  // Cross-service request_events table (shared correlation across admin, scraper, and LLM services)
  await query(`
    CREATE TABLE IF NOT EXISTS request_events (
      id         BIGSERIAL PRIMARY KEY,
      request_id VARCHAR(64) NOT NULL,
      service    VARCHAR(64) NOT NULL DEFAULT 'admin',
      event_type VARCHAR(64) NOT NULL,
      status     VARCHAR(32) NOT NULL DEFAULT 'info',
      message    TEXT,
      metadata   JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_request_events_request_id
    ON request_events(request_id)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_request_events_created_at
    ON request_events(created_at DESC)
  `);

  console.log("[DB] Migration 007 complete — prompt_history, request_events");
}
