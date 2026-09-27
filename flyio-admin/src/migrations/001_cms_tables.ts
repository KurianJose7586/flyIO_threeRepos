import { query } from "../db/pgPool";

/**
 * Migration 001: CMS core tables — pages, site_content, admin_users.
 * Idempotent (IF NOT EXISTS). Runs on every startup.
 */
export async function runMigration001(): Promise<void> {
  console.log("[DB] Running migration 001 — CMS core tables...");

  await query(`
    CREATE TABLE IF NOT EXISTS pages (
      id         SERIAL PRIMARY KEY,
      slug       TEXT NOT NULL UNIQUE,
      title      TEXT NOT NULL,
      body       TEXT NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE TABLE IF NOT EXISTS site_content (
      id         SERIAL PRIMARY KEY,
      key        TEXT NOT NULL UNIQUE,
      title      TEXT,
      body       TEXT NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await query(`
    CREATE TABLE IF NOT EXISTS admin_users (
      id            SERIAL PRIMARY KEY,
      username      TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  console.log("[DB] Migration 001 complete — pages, site_content, admin_users");
}
