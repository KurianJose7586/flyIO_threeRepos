import { Router, Request, Response } from "express";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import { query } from "../db/pgPool";
import { env } from "../config/env";

const router = Router();

/**
 * POST /api/admin/login
 * Authenticates an admin user and returns a JWT.
 * Body: { username, password }
 */
router.post("/api/admin/login", async (req: Request, res: Response) => {
  try {
    const { username, password } = req.body;

    if (!username || !password) {
      res.status(400).json({
        success: false,
        error: "Bad Request",
        detail: "Both 'username' and 'password' are required.",
      });
      return;
    }

    const result = await query(
      "SELECT id, username, password_hash FROM admin_users WHERE username = $1",
      [username]
    );

    if (result.rows.length === 0) {
      res.status(401).json({
        success: false,
        error: "Unauthorized",
        detail: "Invalid username or password.",
      });
      return;
    }

    const admin = result.rows[0];
    const isValid = await bcrypt.compare(password, admin.password_hash);

    if (!isValid) {
      res.status(401).json({
        success: false,
        error: "Unauthorized",
        detail: "Invalid username or password.",
      });
      return;
    }

    const token = jwt.sign(
      { sub: admin.id, username: admin.username, role: "admin" },
      env.CMS_JWT_SECRET,
      { expiresIn: "24h" }
    );

    res.json({
      success: true,
      token,
      admin: { id: admin.id, username: admin.username },
    });
  } catch (err: unknown) {
    const e = err as Error;
    res.status(500).json({
      success: false,
      error: "Internal Server Error",
      detail: e.message || "Login failed",
    });
  }
});

/**
 * GET /api/admin/me
 * Returns the currently authenticated admin's info from their JWT.
 */
router.get("/api/admin/me", (req: Request, res: Response) => {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith("Bearer ")) {
    res.status(401).json({ success: false, error: "Unauthorized" });
    return;
  }

  try {
    const token = authHeader.split(" ")[1];
    const decoded = jwt.verify(token, env.CMS_JWT_SECRET) as {
      sub: string;
      username: string;
    };
    res.json({
      success: true,
      admin: { id: decoded.sub, username: decoded.username },
    });
  } catch {
    res.status(401).json({ success: false, error: "Invalid or expired token" });
  }
});

export default router;
