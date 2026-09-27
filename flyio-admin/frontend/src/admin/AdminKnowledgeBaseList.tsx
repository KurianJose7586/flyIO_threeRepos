import React, { useState, useEffect, useCallback } from "react";
import {
  getKnowledgeBaseEntries,
  getKnowledgeBaseChunks,
  deleteKnowledgeBaseEntry,
  deleteKnowledgeBaseChunk,
} from "./adminApi";
import type { KnowledgeBaseEntry, KnowledgeBaseChunk, Pagination } from "./adminApi";
import { Database, Trash2, Layers, Clock, ChevronLeft, ChevronRight, X, Hash } from "lucide-react";

interface AdminKnowledgeBaseListProps {
  refreshKey: number;
}

/**
 * AdminKnowledgeBaseList (v2)
 *
 * Shows crawled URLs grouped as cards (one card per URL).
 * Each card shows: page_title, source_url, chunk count, fetched_at.
 * "View Chunks" opens an overlay listing all chunks for that URL in the
 * exact pipeline format: section_path, chunk_index, content_text, content_html.
 * Allows deleting entire URL entries or individual chunks from knowledge_base
 * without affecting the history audit log.
 */
export const AdminKnowledgeBaseList: React.FC<AdminKnowledgeBaseListProps> = ({ refreshKey }) => {
  const [entries, setEntries] = useState<KnowledgeBaseEntry[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ total: 0, page: 1, limit: 20, totalPages: 1 });
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Chunk viewer overlay state
  const [viewUrl, setViewUrl] = useState<string | null>(null);
  const [viewTitle, setViewTitle] = useState<string>("");
  const [viewChunks, setViewChunks] = useState<KnowledgeBaseChunk[]>([]);
  const [viewLoading, setViewLoading] = useState(false);
  const [selectedChunk, setSelectedChunk] = useState<KnowledgeBaseChunk | null>(null);

  const loadEntries = useCallback(async (page: number) => {
    setLoading(true);
    try {
      const data = await getKnowledgeBaseEntries(page, pagination.limit);
      setEntries(data.entries);
      setPagination(data.pagination);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load entries: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  }, [pagination.limit]);

  useEffect(() => { loadEntries(1); }, [refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleDelete = async (sourceUrl: string) => {
    if (!confirm(`Delete all knowledge base chunks for:\n${sourceUrl}\n\n(Crawl history records will remain intact.)`)) return;
    try {
      await deleteKnowledgeBaseEntry(sourceUrl);
      setToast({ type: "success", message: "Deleted from knowledge_base. History records remain intact." });
      loadEntries(pagination.page);
    } catch (err: any) {
      setToast({ type: "error", message: "Delete failed: " + (err.response?.data?.detail || err.message) });
    }
  };

  const handleDeleteChunk = async (chunkId: number) => {
    if (!confirm(`Delete chunk #${chunkId} from knowledge_base?\n\n(Crawl history records will remain intact.)`)) return;
    try {
      await deleteKnowledgeBaseChunk(chunkId);
      setToast({ type: "success", message: "Chunk deleted from knowledge_base." });
      if (viewUrl) {
        const updated = viewChunks.filter((c) => c.id !== chunkId);
        setViewChunks(updated);
        setSelectedChunk(null);
        if (updated.length === 0) {
          setViewUrl(null);
        }
      }
      loadEntries(pagination.page);
    } catch (err: any) {
      setToast({ type: "error", message: "Delete failed: " + (err.response?.data?.detail || err.message) });
    }
  };

  const handleViewChunks = async (sourceUrl: string, pageTitle: string) => {
    setViewUrl(sourceUrl);
    setViewTitle(pageTitle);
    setViewChunks([]);
    setSelectedChunk(null);
    setViewLoading(true);
    try {
      const chunks = await getKnowledgeBaseChunks(sourceUrl);
      setViewChunks(chunks);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load chunks: " + (err.message || String(err)) });
      setViewUrl(null);
    } finally {
      setViewLoading(false);
    }
  };

  const formatDate = (dateStr: string) => {
    if (!dateStr) return "";
    try {
      const d = new Date(dateStr.endsWith("Z") ? dateStr : dateStr + "Z");
      return isNaN(d.getTime()) ? dateStr : d.toLocaleDateString("en-IN", {
        day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch { return dateStr; }
  };

  if (loading) {
    return (
      <div className="admin-empty admin-fade-in">
        <div className="admin-empty-icon">⏳</div>
        Loading knowledge base…
      </div>
    );
  }

  return (
    <div className="admin-fade-in">
      {toast && (
        <div className={`admin-toast ${toast.type === "success" ? "admin-toast-success" : "admin-toast-error"}`}>
          {toast.type === "success" ? "✓" : "✕"} {toast.message}
        </div>
      )}

      <div className="admin-section-header">
        <div className="admin-section-title">
          <Database size={14} />
          Knowledge Base ({pagination.total} URL{pagination.total !== 1 ? "s" : ""})
        </div>
        {pagination.total > 0 && (
          <span style={{ fontSize: "0.7rem", color: "var(--admin-text-muted)" }}>
            Page {pagination.page} of {pagination.totalPages}
          </span>
        )}
      </div>

      {entries.length === 0 ? (
        <div className="admin-empty">
          <div className="admin-empty-icon">📭</div>
          No pages stored yet. Use the form above to fetch URLs into the knowledge base.
        </div>
      ) : (
        <>
          {entries.map((entry) => (
            <div key={entry.source_url} className="admin-card" style={{ cursor: "default" }}>
              <div className="admin-card-info">
                <div className="admin-card-title" style={{ fontSize: "0.9rem" }}>
                  {entry.page_title || entry.source_url}
                </div>
                <div className="admin-card-meta">
                  <span
                    className="admin-card-slug"
                    style={{ wordBreak: "break-all", maxWidth: "60%", overflow: "hidden", textOverflow: "ellipsis" }}
                    title={entry.source_url}
                  >
                    {entry.source_url}
                  </span>
                  <span
                    style={{
                      fontSize: "0.68rem",
                      fontWeight: 700,
                      padding: "0.15rem 0.5rem",
                      borderRadius: 9999,
                      background: "var(--admin-accent-bg)",
                      color: "var(--admin-accent)",
                    }}
                  >
                    <Layers size={10} style={{ display: "inline", marginRight: 3 }} />
                    {entry.chunk_count} chunk{entry.chunk_count !== 1 ? "s" : ""}
                  </span>
                  {/* Vector coverage. Chunks reach Postgres immediately but
                      the vector DB in batches, so a page can legitimately sit
                      part-ingested for minutes — show the ratio rather than
                      leaving that to be inferred from empty point IDs. */}
                  {entry.ingested_count !== undefined && (() => {
                    const done = Number(entry.ingested_count);
                    const total = Number(entry.chunk_count);
                    const complete = total > 0 && done >= total;
                    return (
                      <span
                        style={{
                          fontSize: "0.68rem",
                          fontWeight: 700,
                          padding: "0.15rem 0.5rem",
                          borderRadius: 9999,
                          background: complete
                            ? "var(--admin-green-bg)"
                            : done > 0
                            ? "var(--admin-accent-bg)"
                            : "var(--admin-red-bg)",
                          color: complete
                            ? "var(--admin-green)"
                            : done > 0
                            ? "var(--admin-accent)"
                            : "var(--admin-red)",
                        }}
                        title="Chunks stored in the Qdrant vector database"
                      >
                        <Database size={10} style={{ display: "inline", marginRight: 3 }} />
                        {complete ? `${done} vectors` : `${done}/${total} vectors`}
                      </span>
                    );
                  })()}
                  <span className="admin-card-time">
                    <Clock size={11} />
                    {formatDate(entry.fetched_at)}
                  </span>
                </div>
              </div>

              <div className="admin-card-actions">
                <button
                  id={`kb-view-${encodeURIComponent(entry.source_url)}`}
                  className="admin-btn admin-btn-secondary admin-btn-icon"
                  onClick={() => handleViewChunks(entry.source_url, entry.page_title)}
                  title="View chunks"
                >
                  <Layers size={14} />
                </button>
                <button
                  id={`kb-delete-${encodeURIComponent(entry.source_url)}`}
                  className="admin-btn admin-btn-danger admin-btn-icon"
                  onClick={() => handleDelete(entry.source_url)}
                  title="Delete all chunks"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}

          {pagination.totalPages > 1 && (
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center", marginTop: "1.25rem" }}>
              <button
                className="admin-btn admin-btn-secondary admin-btn-icon"
                onClick={() => loadEntries(pagination.page - 1)}
                disabled={pagination.page <= 1}
              >
                <ChevronLeft size={14} />
              </button>
              <span style={{ fontSize: "0.8rem", color: "var(--admin-text-secondary)", display: "flex", alignItems: "center", padding: "0 0.5rem" }}>
                {pagination.page} / {pagination.totalPages}
              </span>
              <button
                className="admin-btn admin-btn-secondary admin-btn-icon"
                onClick={() => loadEntries(pagination.page + 1)}
                disabled={pagination.page >= pagination.totalPages}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Chunks overlay ─────────────────────────────────────────────────── */}
      {viewUrl && (
        <div
          style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.55)",
            backdropFilter: "blur(4px)",
            zIndex: 200,
            display: "flex", alignItems: "flex-start", justifyContent: "center",
            padding: "2rem 1rem",
            overflowY: "auto",
          }}
          onClick={(e) => { if (e.target === e.currentTarget) { setViewUrl(null); setSelectedChunk(null); } }}
        >
          <div style={{
            background: "var(--admin-surface)",
            border: "1px solid var(--admin-border)",
            borderRadius: 16,
            width: "100%", maxWidth: 900,
            boxShadow: "0 20px 60px rgba(0,0,0,0.18)",
            overflow: "hidden",
          }}>
            {/* Header */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "1rem 1.25rem",
              borderBottom: "1px solid var(--admin-border)",
              background: "var(--admin-surface)",
              position: "sticky", top: 0, zIndex: 1,
            }}>
              <div>
                <div style={{ fontSize: "0.9rem", fontWeight: 700, color: "var(--admin-text)" }}>
                  {viewTitle || viewUrl}
                </div>
                <div style={{ fontSize: "0.7rem", color: "var(--admin-accent)", fontFamily: "monospace", marginTop: 2, wordBreak: "break-all" }}>
                  {viewUrl}
                </div>
                {!viewLoading && (
                  <div style={{ fontSize: "0.7rem", color: "var(--admin-text-muted)", marginTop: 2 }}>
                    {viewChunks.length} chunk{viewChunks.length !== 1 ? "s" : ""} stored
                  </div>
                )}
              </div>
              <button className="admin-btn admin-btn-secondary admin-btn-icon" onClick={() => { setViewUrl(null); setSelectedChunk(null); }} title="Close">
                <X size={14} />
              </button>
            </div>

            {viewLoading ? (
              <div className="admin-empty" style={{ padding: "2rem" }}>
                <div className="admin-empty-icon">⏳</div>
                Loading chunks…
              </div>
            ) : viewChunks.length === 0 ? (
              <div className="admin-empty" style={{ padding: "2rem" }}>
                <div className="admin-empty-icon">📭</div>
                No chunks found.
              </div>
            ) : (
              <div style={{ display: "flex", height: "70vh" }}>
                {/* Chunk list sidebar */}
                <div style={{
                  width: 260, flexShrink: 0,
                  borderRight: "1px solid var(--admin-border)",
                  overflowY: "auto",
                  padding: "0.75rem",
                  background: "var(--admin-bg)",
                }}>
                  {viewChunks.map((chunk) => (
                    <button
                      key={chunk.id}
                      onClick={() => setSelectedChunk(chunk)}
                      style={{
                        display: "block", width: "100%", textAlign: "left",
                        padding: "0.55rem 0.75rem",
                        borderRadius: 8,
                        marginBottom: "0.3rem",
                        border: "1px solid",
                        borderColor: selectedChunk?.id === chunk.id ? "var(--admin-accent)" : "var(--admin-border)",
                        background: selectedChunk?.id === chunk.id ? "var(--admin-accent-bg)" : "var(--admin-surface)",
                        cursor: "pointer",
                        transition: "all 0.15s",
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 2 }}>
                        <Hash size={10} color="var(--admin-text-muted)" />
                        <span style={{ fontSize: "0.68rem", fontWeight: 700, color: "var(--admin-text-muted)" }}>
                          chunk {chunk.chunk_index}
                        </span>
                      </div>
                      <div style={{ fontSize: "0.72rem", color: "var(--admin-accent)", marginBottom: 2, fontFamily: "monospace" }}>
                        {chunk.section_path || "(intro)"}
                      </div>
                      <div style={{ fontSize: "0.73rem", color: "var(--admin-text-secondary)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                        {chunk.content_text}
                      </div>
                    </button>
                  ))}
                </div>

                {/* Chunk detail pane */}
                <div style={{ flex: 1, overflowY: "auto", padding: "1.25rem" }}>
                  {!selectedChunk ? (
                    <div style={{ color: "var(--admin-text-muted)", fontSize: "0.85rem", marginTop: "2rem", textAlign: "center" }}>
                      ← Select a chunk to view its content
                    </div>
                  ) : (
                    <>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
                        <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--admin-text)" }}>
                          Chunk #{selectedChunk.chunk_index} Details
                        </div>
                        <button
                          className="admin-btn admin-btn-danger"
                          style={{ padding: "0.3rem 0.65rem", fontSize: "0.72rem" }}
                          onClick={() => handleDeleteChunk(selectedChunk.id)}
                          title="Delete this chunk from knowledge_base"
                        >
                          <Trash2 size={12} />
                          Delete Chunk
                        </button>
                      </div>

                      {/* Metadata strip — same fields as pipeline JSON */}
                      <div style={{
                        background: "var(--admin-bg)",
                        border: "1px solid var(--admin-border)",
                        borderRadius: 8, padding: "0.75rem 1rem",
                        marginBottom: "1rem", fontSize: "0.75rem",
                        fontFamily: "monospace", lineHeight: 1.8,
                        color: "var(--admin-text-secondary)",
                      }}>
                        <div><b>chunk_id</b>:        #{selectedChunk.id}</div>
                        <div>
                          <b>qdrant_point_id</b>:{" "}
                          {selectedChunk.qdrant_point_id ? (
                            <span style={{ color: "var(--admin-accent)" }}>{selectedChunk.qdrant_point_id}</span>
                          ) : selectedChunk.vector_status === "pending" ? (
                            <span style={{ color: "var(--admin-accent)" }}>
                              queued — this crawl is still embedding its chunks
                            </span>
                          ) : (
                            <span style={{ color: "var(--admin-red)" }}>
                              not ingested — no point exists in Qdrant for this chunk
                            </span>
                          )}
                        </div>
                        <div><b>source_url</b>:      {selectedChunk.source_url}</div>
                        <div><b>page_title</b>:      {selectedChunk.page_title}</div>
                        <div><b>section_path</b>:    {selectedChunk.section_path || '""'}</div>
                        <div><b>chunk_index</b>:     {selectedChunk.chunk_index}</div>
                      </div>

                      {/* content_text */}
                      <div style={{ fontWeight: 700, fontSize: "0.75rem", color: "var(--admin-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.07em" }}>
                        content_text
                      </div>
                      <div style={{
                        background: "#f5f7ff",
                        border: "1px solid var(--admin-border)",
                        borderRadius: 8, padding: "0.85rem 1rem",
                        marginBottom: "1rem",
                        fontSize: "0.82rem", lineHeight: 1.7,
                        color: "var(--admin-text)",
                        whiteSpace: "pre-wrap",
                      }}>
                        {selectedChunk.content_text}
                      </div>

                      {/* content_html */}
                      <div style={{ fontWeight: 700, fontSize: "0.75rem", color: "var(--admin-text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.07em" }}>
                        content_html
                      </div>
                      <pre style={{
                        background: "#f8f6ff",
                        border: "1px solid var(--admin-border)",
                        borderRadius: 8, padding: "0.85rem 1rem",
                        fontSize: "0.72rem",
                        fontFamily: "monospace",
                        lineHeight: 1.65,
                        color: "var(--admin-text)",
                        overflowX: "auto",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}>
                        {selectedChunk.content_html}
                      </pre>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
