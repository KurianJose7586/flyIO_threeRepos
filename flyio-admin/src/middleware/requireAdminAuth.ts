import { Request, Response, NextFunction } from "express";
import jwt from "jsonwebtoken";
import { env } from "../config/env";

/**
 * Middleware that requires a valid admin JWT in the Authorization header.
 * Applied to all admin write routes (POST, PUT, DELETE) and protected reads.
 *
 * Reads: Authorization: Bearer <token>
 * Verifies against CMS_JWT_SECRET env var.
 * Returns 401 on missing, invalid, or expired tokens.
 */
export function requireAdminAuth(
  req: Request,
  res: Response,
  next: NextFunction
): void {
  const authHeader = req.headers.authorization;

  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    res.status(401).json({
      success: false,
      error: "Unauthorized",
      detail: "Authentication required. Provide a valid Bearer token.",
    });
    return;
  }

  const token = authHeader.split(" ")[1];

  try {
    const decoded = jwt.verify(token, env.CMS_JWT_SECRET);
    (req as Request & { adminUser: unknown }).adminUser = decoded;
    next();
  } catch (err: unknown) {
    const jwtErr = err as { name?: string };
    if (jwtErr.name === "TokenExpiredError") {
      res.status(401).json({
        success: false,
        error: "Unauthorized",
        detail: "Token has expired. Please log in again.",
      });
      return;
    }
    res.status(401).json({
      success: false,
      error: "Unauthorized",
      detail: "Invalid authentication token.",
    });
  }
}
