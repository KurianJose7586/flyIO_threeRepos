import { runMigration001 } from "./001_cms_tables";
import { runMigration002 } from "./002_blog_posts";
import { runMigration003 } from "./003_trip_packages";
import { runMigration004 } from "./004_jobs_events";
import { runMigration005 } from "./005_knowledge_base";
import { runMigration006 } from "./006_blog_extensions";
import { runMigration007 } from "./007_prompt_history";
import { runMigration008 } from "./008_history_duration";
import { runMigration009 } from "./009_kb_qdrant_point_id";

/**
 * Runs all migrations in order on startup.
 * Each migration is idempotent — safe to re-run.
 */
export async function runAllMigrations(): Promise<void> {
  console.log("[DB] Starting all migrations...");
  await runMigration001();
  await runMigration002();
  await runMigration003();
  await runMigration004();
  await runMigration005();
  await runMigration006();
  await runMigration007();
  await runMigration008();
  await runMigration009();
  console.log("[DB] All migrations complete.");
}
