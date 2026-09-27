import { Pool, PoolClient, QueryResult } from "pg";
import { env } from "../config/env";

/**
 * PostgreSQL connection pool singleton.
 * Reads DATABASE_URL or individual PG* env vars — no hardcoding.
 */
let _pool: Pool | null = null;

function getPool(): Pool {
  if (_pool) return _pool;

  if (env.DATABASE_URL) {
    _pool = new Pool({
      connectionString: env.DATABASE_URL,
      ssl: env.NODE_ENV === "production" ? { rejectUnauthorized: false } : false,
    });
  } else {
    _pool = new Pool({
      host: env.PGHOST,
      port: env.PGPORT,
      user: env.PGUSER,
      password: env.PGPASSWORD,
      database: env.PGDATABASE,
      ssl: false,
    });
  }

  _pool.on("error", (err) => {
    console.error("[PG] Unexpected pool error:", err.message);
  });

  console.log("[PG] Connection pool initialized.");
  return _pool;
}

/**
 * Execute a parameterized query using the pool.
 */
export async function query(
  text: string,
  params?: unknown[]
): Promise<QueryResult> {
  const pool = getPool();
  return pool.query(text, params);
}

/**
 * Get a dedicated client for transactions.
 */
export async function getClient(): Promise<PoolClient> {
  return getPool().connect();
}

/**
 * Close the pool. Called on graceful shutdown.
 */
export async function closePool(): Promise<void> {
  if (_pool) {
    await _pool.end();
    _pool = null;
    console.log("[PG] Connection pool closed.");
  }
}
