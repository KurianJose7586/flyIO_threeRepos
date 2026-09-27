import { query } from "../db/pgPool";

/**
 * Migration 004: jobs + job_events tables for shared job_id tracking.
 * Every scrape operation gets a UUID job_id that flows through both
 * this service and flyio-scraper-service, making operations traceable
 * end-to-end without sharing a database.
 */
export async function runMigration004(): Promise<void> {
  console.log("[DB] Running migration 004 — jobs, job_events...");

  // pgcrypto extension for gen_random_uuid()
  await query(`CREATE EXTENSION IF NOT EXISTS "pgcrypto"`);

  await query(`
    CREATE TABLE IF NOT EXISTS jobs (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      operation  TEXT NOT NULL,
      status     TEXT NOT NULL DEFAULT 'created',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE TABLE IF NOT EXISTS job_events (
      id         BIGSERIAL PRIMARY KEY,
      job_id     UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      event_type TEXT NOT NULL,
      detail     JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_job_events_job_id
    ON job_events(job_id)
  `);

  console.log("[DB] Migration 004 complete — jobs, job_events");
}
