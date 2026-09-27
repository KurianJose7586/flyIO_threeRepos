import { query } from "../db/pgPool";

/**
 * Migration 008: Add duration_ms column to history table.
 *
 * Stores how many milliseconds a URL took to scrape (from job
 * created_at to when the history row was written). Uses
 * ADD COLUMN IF NOT EXISTS so it is safe to re-run.
 */
export async function runMigration008(): Promise<void> {
  console.log("[DB] Running migration 008 — history.duration_ms...");

  await query(`
    ALTER TABLE history
    ADD COLUMN IF NOT EXISTS duration_ms INTEGER
  `);

  console.log("[DB] Migration 008 complete — history.duration_ms");
}
