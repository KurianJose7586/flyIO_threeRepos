import { query } from "../db/pgPool";

/**
 * Migration 009: Add qdrant_point_id column to knowledge_base.
 *
 * Records the point ID the LLM Store API actually returned for a chunk,
 * so the admin UI reports what is really in Qdrant. Previously the chunks
 * endpoint recomputed the ID from (source_url, section_path, chunk_index)
 * on every read, which meant every chunk displayed a plausible-looking ID
 * whether or not it had ever been ingested — a point lookup for a chunk
 * that was never pushed just came back empty with nothing to explain why.
 *
 * NULL means "not ingested into the vector DB (yet)".
 * Uses ADD COLUMN IF NOT EXISTS so it is safe to re-run.
 */
export async function runMigration009(): Promise<void> {
  console.log("[DB] Running migration 009 — knowledge_base.qdrant_point_id...");

  await query(`
    ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS qdrant_point_id TEXT
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_kb_qdrant_point_id
    ON knowledge_base(qdrant_point_id)
  `);

  console.log("[DB] Migration 009 complete — knowledge_base.qdrant_point_id");
}
