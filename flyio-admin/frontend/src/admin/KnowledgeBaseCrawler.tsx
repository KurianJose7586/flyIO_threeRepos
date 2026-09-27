import React, { useState, useEffect, useRef, useCallback } from "react";
import { submitCrawlUrls, getJobUrlResults } from "./adminApi";
import type { JobUrlResult } from "./adminApi";
import {
  Globe, CheckCircle2, XCircle, Loader2, Send, Clock, Database, AlertTriangle,
} from "lucide-react";

/**
 * KnowledgeBaseCrawler
 *
 * On submit → immediately shows a "queued" card for every URL.
 * Fires an async job and polls /api/admin/jobs/:id/url-results every 2 s.
 * Each URL card updates independently with its own status, error, chunk count,
 * and elapsed time. Polling stops when all URLs reach a terminal state.
 */

type UrlCardState = {
  url: string;
  status: "queued" | "running" | "success" | "failed" | "pending" | string;
  chunks: number;
  /** Chunks that reached Qdrant — see JobUrlResult.vector_chunks. */
  vector_chunks?: number;
  vector_status?: "stored" | "partial" | "failed" | "pending" | null;
  error: string | null;
  duration_ms: number | null;
  startedAt: number; // local timestamp when card was shown (for live timer)
};

const POLL_INTERVAL_MS = 2000;
const TERMINAL = new Set(["success", "failed"]);

function formatDuration(ms: number | null, startedAt: number): string {
  const elapsed = ms !== null ? ms : Date.now() - startedAt;
  if (elapsed < 1000) return `${elapsed}ms`;
  return `${(elapsed / 1000).toFixed(1)}s`;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "success")
    return <CheckCircle2 size={15} color="var(--admin-green)" />;
  if (status === "failed")
    return <XCircle size={15} color="var(--admin-red)" />;
  if (status === "running")
    return <Loader2 size={15} color="var(--admin-accent)" style={{ animation: "spin 1s linear infinite" }} />;
  // queued / pending
  return <Clock size={15} color="var(--admin-text-muted)" />;
}

function statusBadge(status: string) {
  const styles: Record<string, React.CSSProperties> = {
    success: { background: "var(--admin-green-bg)", color: "var(--admin-green)" },
    failed:  { background: "var(--admin-red-bg)",   color: "var(--admin-red)" },
    running: { background: "var(--admin-accent-bg)", color: "var(--admin-accent)" },
  };
  const s = styles[status] ?? { background: "var(--admin-border)", color: "var(--admin-text-muted)" };
  return (
    <span style={{
      fontSize: "0.65rem", fontWeight: 700, padding: "0.2rem 0.55rem",
      borderRadius: 9999, flexShrink: 0, textTransform: "capitalize", ...s,
    }}>
      {status}
    </span>
  );
}

export const KnowledgeBaseCrawler: React.FC<{ onCrawlComplete: () => void }> = ({
  onCrawlComplete,
}) => {
  const [urlText, setUrlText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [urlCards, setUrlCards] = useState<UrlCardState[]>([]);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // used to refresh live timers
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const ACTIVE_JOB_KEY = "flyio_active_crawl_job";

  const clearActiveJob = useCallback(() => {
    try { localStorage.removeItem(ACTIVE_JOB_KEY); } catch {}
  }, []);

  const saveActiveJob = useCallback((jId: string, urls: string[], startedAt: number) => {
    try {
      localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ jobId: jId, urls, startedAt }));
    } catch {}
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
  }, []);

  // Live elapsed-time ticker (1 s refresh while job is running)
  const startTicker = useCallback(() => {
    tickRef.current = setInterval(() => setTick((t) => t + 1), 1000);
  }, []);

  const startPolling = useCallback((jId: string, submittedUrls: string[]) => {
    pollRef.current = setInterval(async () => {
      try {
        const data = await getJobUrlResults(jId);
        setJobStatus(data.job_status);

        // Build a lookup of resolved URLs from history
        const resolvedMap = new Map<string, JobUrlResult>();
        for (const r of data.urls) resolvedMap.set(r.url, r);

        setUrlCards((prev) =>
          prev.map((card) => {
            const resolved = resolvedMap.get(card.url);
            if (!resolved) {
              // Not yet in history — if job is finalized, mark unresolved cards as failed
              if (TERMINAL.has(data.job_status)) {
                return {
                  ...card,
                  status: "failed",
                  error: "Scrape job failed or produced no output",
                };
              }
              return {
                ...card,
                status: data.job_status === "running" || data.job_status === "sent" ? "running" : card.status,
              };
            }
            return {
              ...card,
              status: resolved.status,
              chunks: resolved.chunks,
              vector_chunks: resolved.vector_chunks,
              vector_status: resolved.vector_status,
              error: resolved.error,
              duration_ms: resolved.duration_ms,
            };
          })
        );

        // Stop when all submitted URLs have resolved
        const allDone = submittedUrls.every((u) => {
          const resolved = resolvedMap.get(u);
          return resolved && TERMINAL.has(resolved.status);
        });

        if (allDone || TERMINAL.has(data.job_status)) {
          stopPolling();
          clearActiveJob();
          setSubmitting(false);
          onCrawlComplete();
        }
      } catch {
        // Swallow poll errors — backend may still be starting up
      }
    }, POLL_INTERVAL_MS);
  }, [stopPolling, onCrawlComplete, clearActiveJob]);

  // Restore active background job on mount (page refresh or tab switch)
  useEffect(() => {
    const restoreActiveJob = async () => {
      let saved: { jobId: string; urls: string[]; startedAt: number } | null = null;
      try {
        const raw = localStorage.getItem(ACTIVE_JOB_KEY);
        if (raw) saved = JSON.parse(raw);
      } catch {}

      if (saved && saved.jobId && Array.isArray(saved.urls) && saved.urls.length > 0) {
        setJobId(saved.jobId);
        setSubmitting(true);
        setJobStatus("running");
        setUrlCards(
          saved.urls.map((url) => ({
            url,
            status: "running",
            chunks: 0,
            error: null,
            duration_ms: null,
            startedAt: saved.startedAt || Date.now(),
          }))
        );
        startTicker();
        startPolling(saved.jobId, saved.urls);

        // Immediate poll on restore
        try {
          const initialData = await getJobUrlResults(saved.jobId);
          if (TERMINAL.has(initialData.job_status)) {
            clearActiveJob();
          }
        } catch {}
      }
    };

    restoreActiveJob();
  }, [startPolling, startTicker, clearActiveJob]);

  const handleSubmit = async () => {
    if (!urlText.trim()) return;

    const submittedUrls = urlText
      .split("\n")
      .map((u) => u.trim())
      .filter(Boolean);

    if (submittedUrls.length === 0) return;

    // Catch bare words / missing scheme before starting a job the scraper
    // can't run (e.g. "gorakhpur" instead of a full page URL).
    const invalidUrls = submittedUrls.filter((u) => {
      try {
        const p = new URL(u);
        return !(p.protocol === "http:" || p.protocol === "https:") || !p.hostname;
      } catch {
        return true;
      }
    });
    if (invalidUrls.length > 0) {
      setGlobalError(
        `Not a valid URL: ${invalidUrls.join(", ")}. Paste full page links starting with https://, e.g. https://en.wikivoyage.org/wiki/Gorakhpur`
      );
      return;
    }

    // 1. Immediately show queued cards for every URL
    const now = Date.now();
    setUrlCards(submittedUrls.map((url) => ({
      url, status: "queued", chunks: 0, error: null, duration_ms: null, startedAt: now,
    })));
    setSubmitting(true);
    setJobId(null);
    setJobStatus("queued");
    setGlobalError(null);
    stopPolling();

    try {
      // 2. Fire async job — returns job_id immediately
      const response = await submitCrawlUrls(urlText, { asyncMode: true });

      if (!response.job_id) {
        // Sync response (backend returned results directly)
        if (response.results) {
          setUrlCards(response.results.map((r, i) => ({
            url: r.url || submittedUrls[i] || "Unknown",
            status: r.status,
            chunks: r.chunks ?? 0,
            vector_chunks: r.vector_stored,
            vector_status: r.vector_status === "skipped" ? "failed" : r.vector_status,
            error: r.error ?? null,
            duration_ms: null,
            startedAt: now,
          })));
        }
        setJobStatus(response.status ?? "success");
        setSubmitting(false);
        onCrawlComplete();
        return;
      }

      // 3. Got job_id — persist to localStorage and start polling
      saveActiveJob(response.job_id, submittedUrls, now);
      setJobId(response.job_id);
      setJobStatus(response.status ?? "pending");
      setUrlCards((prev) =>
        prev.map((c) => ({ ...c, status: "running" }))
      );
      startTicker();
      startPolling(response.job_id, submittedUrls);
    } catch (err: any) {
      setSubmitting(false);
      clearActiveJob();
      setGlobalError(
        err.response?.data?.detail ||
        err.response?.data?.error ||
        err.message ||
        "Failed to submit URLs"
      );
      setUrlCards((prev) =>
        prev.map((c) => ({
          ...c,
          status: "failed",
          error: err.response?.data?.detail || err.message || "Submission failed",
        }))
      );
      stopPolling();
    }
  };

  // Cleanup on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  const urlCount = urlText.split("\n").map((u) => u.trim()).filter(Boolean).length;

  // Summary counts from cards
  const doneCards = urlCards.filter((c) => TERMINAL.has(c.status));
  const successCount = urlCards.filter((c) => c.status === "success").length;
  const failedCount = urlCards.filter((c) => c.status === "failed").length;
  const allDone = urlCards.length > 0 && doneCards.length === urlCards.length;

  return (
    <div className="admin-editor admin-fade-in">
      {/* Keyframes */}
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes slideIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>

      {/* Header */}
      <div className="admin-editor-header">
        <div style={{
          width: 34, height: 34, borderRadius: 10,
          background: "linear-gradient(135deg, var(--admin-accent), var(--admin-pink))",
          display: "flex", alignItems: "center", justifyContent: "center",
          color: "#fff", flexShrink: 0,
        }}>
          <Globe size={16} />
        </div>
        <div>
          <div className="admin-editor-title">Fetch URLs into Knowledge Base</div>
          <div style={{ fontSize: "0.75rem", color: "var(--admin-text-muted)", marginTop: 2 }}>
            Paste one URL per line — click Submit to fetch and store
          </div>
        </div>
      </div>

      {/* URL textarea */}
      <div className="admin-field">
        <label className="admin-field-label" htmlFor="kb-url-input">
          URLs{" "}
          {urlCount > 0 && (
            <span style={{ color: "var(--admin-accent)", fontWeight: 600, textTransform: "none", letterSpacing: 0 }}>
              ({urlCount} detected)
            </span>
          )}
        </label>
        <textarea
          id="kb-url-input"
          className="admin-textarea"
          style={{ minHeight: 160, fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace", fontSize: "0.85rem" }}
          placeholder={"https://example.com\nhttps://another-site.com/page\nhttps://docs.example.org/guide"}
          value={urlText}
          onChange={(e) => setUrlText(e.target.value)}
          disabled={submitting}
        />
      </div>

      {/* Submit row */}
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
        <button
          id="kb-submit-btn"
          className="admin-btn admin-btn-primary"
          onClick={handleSubmit}
          disabled={submitting || urlCount === 0}
          style={{ padding: "0.6rem 1.4rem" }}
        >
          {submitting ? (
            <>
              <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
              {jobStatus === "running" ? "Scraping in progress…" : "Queued & waiting…"}
            </>
          ) : (
            <>
              <Send size={14} />
              Submit {urlCount > 0 ? `${urlCount} URL${urlCount !== 1 ? "s" : ""}` : "URLs"}
            </>
          )}
        </button>

        {(urlCards.length > 0 || globalError) && (
          <button
            className="admin-btn admin-btn-secondary"
            disabled={submitting}
            onClick={() => {
              stopPolling();
              setUrlCards([]);
              setUrlText("");
              setGlobalError(null);
              setJobId(null);
              setJobStatus(null);
              setSubmitting(false);
            }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Global submission error */}
      {globalError && (
        <div className="admin-toast admin-toast-error" style={{ marginTop: "1.25rem" }}>
          <AlertTriangle size={14} style={{ flexShrink: 0 }} />
          {globalError}
        </div>
      )}

      {/* Per-URL progress cards */}
      {urlCards.length > 0 && (
        <div style={{ marginTop: "1.5rem" }}>

          {/* Summary bar */}
          {urlCards.length > 0 && (
            <div style={{ display: "flex", gap: "0.6rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
              <span style={{
                fontSize: "0.75rem", fontWeight: 600, padding: "0.25rem 0.7rem",
                borderRadius: 9999, background: "var(--admin-accent-bg)", color: "var(--admin-accent)",
              }}>
                {urlCards.length} URL{urlCards.length !== 1 ? "s" : ""}
              </span>
              {successCount > 0 && (
                <span style={{
                  fontSize: "0.75rem", fontWeight: 600, padding: "0.25rem 0.7rem",
                  borderRadius: 9999, background: "var(--admin-green-bg)", color: "var(--admin-green)",
                }}>
                  ✓ {successCount} saved
                </span>
              )}
              {failedCount > 0 && (
                <span style={{
                  fontSize: "0.75rem", fontWeight: 600, padding: "0.25rem 0.7rem",
                  borderRadius: 9999, background: "var(--admin-red-bg)", color: "var(--admin-red)",
                }}>
                  ✕ {failedCount} failed
                </span>
              )}
              {!allDone && submitting && (
                <span style={{
                  fontSize: "0.72rem", color: "var(--admin-text-muted)",
                  display: "flex", alignItems: "center", gap: "0.3rem",
                }}>
                  <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />
                  {doneCards.length}/{urlCards.length} done
                </span>
              )}
              {allDone && (
                <span style={{ fontSize: "0.72rem", color: "var(--admin-text-muted)", fontWeight: 600 }}>
                  ✓ All complete
                </span>
              )}
              {jobId && (
                <span style={{ fontSize: "0.65rem", color: "var(--admin-text-muted)", fontFamily: "monospace" }}>
                  job: {jobId.slice(0, 8)}…
                </span>
              )}
            </div>
          )}

          {/* URL cards */}
          {urlCards.map((card, i) => {
            const isSuccess = card.status === "success";
            const isFailed  = card.status === "failed";
            const isRunning = card.status === "running";
            const isQueued  = card.status === "queued" || card.status === "pending";

            return (
              <div
                key={card.url + i}
                className="admin-card"
                style={{
                  cursor: "default", marginBottom: "0.5rem",
                  animation: "slideIn 0.25s ease",
                  borderLeft: isFailed
                    ? "3px solid var(--admin-red)"
                    : isSuccess
                    ? "3px solid var(--admin-green)"
                    : isRunning
                    ? "3px solid var(--admin-accent)"
                    : "3px solid var(--admin-border)",
                }}
              >
                <div className="admin-card-info" style={{ flex: 1, minWidth: 0 }}>
                  {/* URL row */}
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                    <StatusIcon status={card.status} />
                    <span
                      style={{
                        fontSize: "0.8rem", fontFamily: "monospace",
                        wordBreak: "break-all",
                        color: isFailed ? "var(--admin-red)" : isSuccess ? "var(--admin-green)" : "var(--admin-text)",
                      }}
                    >
                      {card.url}
                    </span>
                  </div>

                  {/* Meta row: chunks + time */}
                  <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.35rem", flexWrap: "wrap", alignItems: "center" }}>
                    {isSuccess && card.chunks > 0 && (
                      <span style={{
                        display: "flex", alignItems: "center", gap: "0.2rem",
                        fontSize: "0.68rem", fontWeight: 700,
                        color: "var(--admin-accent)", background: "var(--admin-accent-bg)",
                        padding: "0.1rem 0.45rem", borderRadius: 9999,
                      }}>
                        <Database size={10} />
                        {card.chunks} chunks
                      </span>
                    )}

                    {/* Vector DB ingestion — a URL is only searchable once its
                        chunks reach Qdrant, so report that separately from the
                        scrape rather than letting "success" imply both. */}
                    {isSuccess && card.vector_status && (
                      <span style={{
                        display: "flex", alignItems: "center", gap: "0.2rem",
                        fontSize: "0.68rem", fontWeight: 700,
                        padding: "0.1rem 0.45rem", borderRadius: 9999,
                        color: card.vector_status === "stored"
                          ? "var(--admin-green)"
                          : card.vector_status === "failed"
                          ? "var(--admin-red)"
                          : "var(--admin-accent)",
                        background: card.vector_status === "stored"
                          ? "var(--admin-green-bg)"
                          : card.vector_status === "failed"
                          ? "var(--admin-red-bg)"
                          : "var(--admin-accent-bg)",
                      }}>
                        <Database size={10} />
                        {card.vector_status === "stored"
                          ? `${card.vector_chunks ?? card.chunks} vectors`
                          : card.vector_status === "partial"
                          ? `${card.vector_chunks ?? 0}/${card.chunks} vectors`
                          : card.vector_status === "pending"
                          ? "embedding…"
                          : "not in vector DB"}
                      </span>
                    )}

                    {/* Elapsed time */}
                    {(isRunning || isSuccess || isFailed) && (
                      <span style={{
                        display: "flex", alignItems: "center", gap: "0.2rem",
                        fontSize: "0.68rem", color: "var(--admin-text-muted)",
                      }}>
                        <Clock size={10} />
                        {/* tick used to force re-render for live timer */}
                        {tick >= 0 && formatDuration(card.duration_ms, card.startedAt)}
                      </span>
                    )}

                    {isQueued && (
                      <span style={{ fontSize: "0.68rem", color: "var(--admin-text-muted)" }}>
                        Waiting in queue…
                      </span>
                    )}
                  </div>

                  {/* Error message (any error — not just robots.txt) */}
                  {isFailed && card.error && (
                    <div style={{
                      marginTop: "0.4rem", fontSize: "0.73rem",
                      color: "var(--admin-red)", fontFamily: "monospace",
                      background: "var(--admin-red-bg)", padding: "0.35rem 0.6rem",
                      borderRadius: 6, wordBreak: "break-word",
                    }}>
                      {card.error}
                    </div>
                  )}
                </div>

                {/* Status badge */}
                <div style={{ flexShrink: 0, alignSelf: "flex-start", paddingTop: 2 }}>
                  {statusBadge(card.status)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
