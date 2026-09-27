import { query } from "../db/pgPool";

/**
 * Migration 003: trip_packages table.
 * Idempotent (IF NOT EXISTS).
 */
export async function runMigration003(): Promise<void> {
  console.log("[DB] Running migration 003 — trip_packages...");

  await query(`
    CREATE TABLE IF NOT EXISTS trip_packages (
      id             SERIAL PRIMARY KEY,
      slug           TEXT NOT NULL UNIQUE,
      title          TEXT NOT NULL,
      description    TEXT NOT NULL,
      itinerary_json TEXT NOT NULL,
      images         TEXT,
      price_tier     TEXT,
      published_at   TIMESTAMPTZ,
      created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_trip_packages_slug
    ON trip_packages(slug)
  `);

  await query(`
    CREATE INDEX IF NOT EXISTS idx_trip_packages_published
    ON trip_packages(published_at)
  `);

  console.log("[DB] Migration 003 complete — trip_packages");
}
