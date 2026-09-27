/**
 * Local PostgreSQL for flyio-admin, with nothing to install: the official
 * PostgreSQL 16 binaries come from the embedded-postgres npm package, which
 * `npm install` fetches for this platform.
 *
 *   node scripts/local-db.mjs          start it; runs until Ctrl+C
 *   node scripts/local-db.mjs --wait   exit 0 once the admin's database
 *                                      accepts connections (for start order)
 *
 * The connection comes from flyio-admin/.env (DATABASE_URL, else PGHOST,
 * PGPORT, PGUSER, PGPASSWORD, PGDATABASE), so this serves exactly the database
 * the admin connects to. If .env points at another machine there is nothing to
 * start and both modes exit at once. Data persists in flyio-admin/.local-db/.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import pg from "pg";
import EmbeddedPostgres from "embedded-postgres";

const adminDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const dataDir = path.join(adminDir, ".local-db");
const waitMode = process.argv.includes("--wait");
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

function readTarget() {
  const envPath = path.join(adminDir, ".env");
  if (!fs.existsSync(envPath)) {
    throw new Error("flyio-admin/.env not found. Run setup.ps1 first.");
  }
  const env = dotenv.parse(fs.readFileSync(envPath));
  if (env.DATABASE_URL) {
    const u = new URL(env.DATABASE_URL);
    return {
      host: u.hostname,
      port: Number(u.port || 5432),
      user: decodeURIComponent(u.username),
      password: decodeURIComponent(u.password),
      database: u.pathname.replace(/^\//, ""),
    };
  }
  return {
    host: env.PGHOST || "",
    port: Number(env.PGPORT || 5432),
    user: env.PGUSER || "",
    password: env.PGPASSWORD || "",
    database: env.PGDATABASE || "",
  };
}

/** Resolves true if the admin's own credentials can open its database. */
async function canConnect(t, database = t.database) {
  const client = new pg.Client({
    host: t.host, port: t.port, user: t.user, password: t.password, database,
    connectionTimeoutMillis: 2000,
  });
  try {
    await client.connect();
    return true;
  } catch (err) {
    canConnect.lastError = err;
    return false;
  } finally {
    await client.end().catch(() => {});
  }
}

// Long enough for a first run's cluster creation on a slow disk; short enough
// that a database which failed to start (its own window says why) does not
// leave the admin waiting for minutes.
const WAIT_SECONDS = 60;

async function waitUntilReady(t) {
  const deadline = Date.now() + WAIT_SECONDS * 1000;
  while (Date.now() < deadline) {
    if (await canConnect(t)) return true;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function main() {
  const t = readTarget();
  const where = `${t.host}:${t.port}/${t.database}`;

  if (!LOCAL_HOSTS.has(t.host)) {
    console.log(`[local-db] flyio-admin/.env uses the database at ${where}; nothing to start here.`);
    return 0;
  }
  if (!t.user || !t.database) {
    throw new Error("flyio-admin/.env needs PGUSER and PGDATABASE (or DATABASE_URL). Run setup.ps1.");
  }

  if (waitMode) {
    console.log(`[local-db] waiting for ${where} ...`);
    if (await waitUntilReady(t)) {
      console.log("[local-db] database ready");
      return 0;
    }
    console.error(
      `[local-db] ${where} did not become ready in ${WAIT_SECONDS}s (${canConnect.lastError?.message}). ` +
        "Check the database's own output for why it did not start."
    );
    return 1;
  }

  // Something may already serve this port - a Postgres you run yourself, or
  // this script in another window. If it takes the admin's credentials, use it.
  if (await canConnect(t)) {
    console.log(`[local-db] a database is already running at ${where}; using it.`);
    return 0;
  }

  const isRootOnPosix = typeof process.getuid === "function" && process.getuid() === 0;
  const server = new EmbeddedPostgres({
    databaseDir: dataDir,
    port: t.port,
    user: t.user,
    password: t.password,
    authMethod: "scram-sha-256",
    persistent: true,
    // Postgres refuses to run as root; only relevant in Linux containers.
    createPostgresUser: isRootOnPosix,
    onLog: () => {},
    onError: (e) => console.error("[local-db]", e instanceof Error ? e.message : String(e).trim()),
  });

  const fresh = !fs.existsSync(path.join(dataDir, "PG_VERSION"));
  if (fresh) {
    console.log(`[local-db] creating a new database cluster in ${dataDir} (first run only)`);
    await server.initialise();
  } else {
    // A hard stop (closing the window, Ctrl+C on Windows) leaves the lock
    // file behind, and a stale one blocks the next start. Nothing answered
    // on the port above, so no server owns it.
    const lock = path.join(dataDir, "postmaster.pid");
    if (fs.existsSync(lock)) fs.rmSync(lock);
  }

  await server.start();

  const admin = new pg.Client({ host: t.host, port: t.port, user: t.user, password: t.password, database: "postgres" });
  try {
    await admin.connect();
  } catch (err) {
    await server.stop().catch(() => {});
    throw new Error(
      `the database in ${dataDir} rejected the credentials in flyio-admin/.env (${err.message}). ` +
        "It was created with different ones: restore them, or delete that folder to start empty."
    );
  }
  const exists = await admin.query("SELECT 1 FROM pg_database WHERE datname = $1", [t.database]);
  if (exists.rowCount === 0) {
    await admin.query(`CREATE DATABASE "${t.database.replace(/"/g, '""')}"`);
    console.log(`[local-db] created database ${t.database}`);
  }
  await admin.end();

  console.log(`[local-db] PostgreSQL 16 ready at ${where}. Ctrl+C to stop.`);

  let stopping = false;
  const shutdown = async () => {
    if (stopping) return;
    stopping = true;
    console.log("[local-db] stopping");
    await server.stop().catch(() => {});
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  // Keep the process alive while the server runs.
  setInterval(() => {}, 1 << 30);
  return null;
}

main().then(
  (code) => {
    if (code !== null) process.exit(code);
  },
  (err) => {
    console.error(`[local-db] ${err.message}`);
    process.exit(1);
  }
);
