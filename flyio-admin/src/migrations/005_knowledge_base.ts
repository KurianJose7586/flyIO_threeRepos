import { query } from "../db/pgPool";

/**
 * Migration 005: knowledge_base + history tables.
 *
 * knowledge_base — stores clean extracted text from scraper results,
 *   tagged with the job_id that produced them.
 * history — audit log of every URL fetch attempt (success/failed),
 *   also tagged with job_id.
 */
export async function runMigration005(): Promise<void> {
  console.log("[DB] Running migration 005 — knowledge_base, history...");

  await query(`
    CREATE TABLE IF NOT EXISTS knowledge_base (
      id                 BIGSERIAL PRIMARY KEY,
      source_url         TEXT NOT NULL,
      chunk_data         JSONB NOT NULL,
      extracted_content  TEXT,
      extracted_metadata JSONB,
      job_id             UUID REFERENCES jobs(id),
      created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_kb_source_url
    ON knowledge_base(source_url)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_kb_chunk_data
    ON knowledge_base USING gin (chunk_data)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_kb_job_id
    ON knowledge_base(job_id)
  `);

  await query(`
    CREATE TABLE IF NOT EXISTS history (
      id            BIGSERIAL PRIMARY KEY,
      url           TEXT NOT NULL,
      status        TEXT NOT NULL DEFAULT 'pending',
      error_message TEXT,
      job_id        UUID REFERENCES jobs(id),
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_history_url
    ON history(url)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_history_job_id
    ON history(job_id)
  `);

  console.log("[DB] Migration 005 complete — knowledge_base, history");
}
