import { Router, Request, Response } from "express";
import { query } from "../db/pgPool";

const router = Router();

/** GET /health — no auth required */
router.get("/health", async (_req: Request, res: Response) => {
  try {
    await query("SELECT 1");
    res.json({ status: "ok", db: "connected" });
  } catch {
    res.status(503).json({ status: "error", db: "unreachable" });
  }
});

export default router;
