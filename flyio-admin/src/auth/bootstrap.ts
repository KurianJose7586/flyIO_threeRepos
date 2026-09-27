import { query } from "../db/pgPool";
import bcrypt from "bcryptjs";

/**
 * Auto-bootstrap the first admin user from environment variables.
 *
 * On startup, if admin_users is empty AND INITIAL_ADMIN_USERNAME +
 * INITIAL_ADMIN_PASSWORD are both set, creates the first admin account
 * with a bcrypt-hashed password.
 *
 * After creation, remove those env vars from your secrets/environment.
 */
export async function bootstrapAdmin(): Promise<void> {
  const username = process.env.INITIAL_ADMIN_USERNAME;
  const password = process.env.INITIAL_ADMIN_PASSWORD;

  if (!username || !password) {
    return; // No bootstrap vars set — skip silently
  }

  const existing = await query(
    "SELECT id, password_hash FROM admin_users WHERE username = $1",
    [username]
  );

  const SALT_ROUNDS = 12;
  const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);

  if (existing.rows.length === 0) {
    await query(
      "INSERT INTO admin_users (username, password_hash) VALUES ($1, $2)",
      [username, passwordHash]
    );
    console.log(`[Auth] Initial admin user "${username}" created.`);
  } else {
    const isMatch = await bcrypt.compare(password, existing.rows[0].password_hash);
    if (!isMatch) {
      await query("UPDATE admin_users SET password_hash = $1 WHERE id = $2", [
        passwordHash,
        existing.rows[0].id,
      ]);
      console.log(
        `[Auth] Admin user "${username}" password synchronized with INITIAL_ADMIN_PASSWORD from environment.`
      );
    }
  }
}
