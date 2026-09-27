import "dotenv/config";
import express, { Request, Response, NextFunction } from "express";
import path from "path";
import { env } from "./config/env";
import { runAllMigrations } from "./migrations/runAll";
import { bootstrapAdmin } from "./auth/bootstrap";
import { closePool } from "./db/pgPool";
import { startBackgroundJobScheduler, stopBackgroundJobScheduler } from "./services/jobScheduler";

// Routes
import healthRouter      from "./routes/health";
import authRouter        from "./routes/auth";
import cmsRouter         from "./routes/cms";
import blogRouter        from "./routes/blog";
import tripPackagesRouter from "./routes/tripPackages";
import knowledgeBaseRouter from "./routes/knowledgeBase";
import scrapeRouter      from "./routes/scrape";
import blogTaxonomyRouter from "./routes/blogTaxonomy";
import llmRouter         from "./routes/llm";
import promptHistoryRouter from "./routes/promptHistory";
import docsRouter        from "./routes/docs";

const app = express();

// ─── Middleware ───────────────────────────────────────────────
app.use(express.json({ limit: "2mb" }));
app.use(express.urlencoded({ extended: true }));

// ─── Serve built frontend (production) ───────────────────────
const frontendDist = path.join(__dirname, "../frontend/dist");
app.use(express.static(frontendDist));

// ─── Serve blog uploads (banner images) ──────────────────────
const uploadDirName = path.basename(env.BLOG_UPLOAD_DIR);
app.use(`/uploads/${uploadDirName}`, express.static(path.resolve(env.BLOG_UPLOAD_DIR)));

// ─── API Routes ───────────────────────────────────────────────
app.use(docsRouter);
app.use(healthRouter);
app.use(authRouter);
app.use(cmsRouter);
app.use(blogRouter);
app.use(blogTaxonomyRouter);
app.use(tripPackagesRouter);
app.use(knowledgeBaseRouter);
app.use(scrapeRouter);
app.use(llmRouter);
app.use(promptHistoryRouter);

// ─── SPA fallback (serve index.html for /admin, /blog, /trips, /page) ───
app.get(/^\/(admin|blog|trips|page)(\/.*)?$/, (_req: Request, res: Response) => {
  res.sendFile(path.join(frontendDist, "index.html"));
});

// ─── 404 ──────────────────────────────────────────────────────
app.use((req: Request, res: Response) => {
  res.status(404).json({
    error: "Not Found",
    detail: `Route ${req.method} ${req.url} does not exist.`,
  });
});

// ─── Global error handler ─────────────────────────────────────
app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  const e = err as Error & { status?: number };
  const status = e.status || 500;
  console.error("[Error]", e.message, e.stack);
  res.status(status).json({
    success: false,
    error: "Server Error",
    detail: e.message || "An unexpected error occurred.",
  });
});

// ─── Startup ──────────────────────────────────────────────────
let isShuttingDown = false;

const server = app.listen(env.PORT, async () => {
  console.log("==============================================");
  console.log(`flyio-admin running on port ${env.PORT}`);
  console.log(`NODE_ENV: ${env.NODE_ENV}`);
  console.log("==============================================");

  try {
    await runAllMigrations();
    await bootstrapAdmin();
    startBackgroundJobScheduler();
    console.log("[Startup] Ready.");
  } catch (err: unknown) {
    const e = err as Error;
    console.error(`[Startup] FAILED: ${e.message}`);
    process.exit(1);
  }
});

// ─── Graceful shutdown ────────────────────────────────────────
async function gracefulShutdown(signal: string): Promise<void> {
  if (isShuttingDown) return;
  isShuttingDown = true;
  console.log(`\n[Shutdown] ${signal} received — closing server`);
  stopBackgroundJobScheduler();

  server.close(async () => {
    await closePool();
    console.log("[Shutdown] Clean exit.");
    process.exit(0);
  });

  setTimeout(() => {
    console.error("[Shutdown] Forced exit after 15s timeout.");
    process.exit(1);
  }, 15_000).unref();
}

process.on("SIGTERM", () => gracefulShutdown("SIGTERM"));
process.on("SIGINT",  () => gracefulShutdown("SIGINT"));

export default app;
