import React, { useState, useEffect } from "react";
import { getCrawlHistory, deleteCrawlHistoryEntry, deleteCrawlHistoryEntries, clearAllCrawlHistory } from "./adminApi";
import type { CrawlHistoryEntry, Pagination } from "./adminApi";
import { History, CheckCircle2, XCircle, Clock, ChevronLeft, ChevronRight, Trash2 } from "lucide-react";

/**
 * AdminCrawlHistory
 *
 * List of all URL fetch attempts, newest first.
 * Shows URL, success/failed status badge, error message (if any), and timestamp.
 * Allows tick-selecting multiple entries to delete in bulk (e.g. 3 of 5),
 * deleting individual entries, or clearing all history.
 * Paginated for large logs.
 */
export const AdminCrawlHistory: React.FC = () => {
  const [entries, setEntries] = useState<CrawlHistoryEntry[]>([]);
  const [pagination, setPagination] = useState<Pagination>({ total: 0, page: 1, limit: 50, totalPages: 1 });
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [deletingSelected, setDeletingSelected] = useState(false);

  const loadHistory = async (page: number) => {
    setLoading(true);
    try {
      const data = await getCrawlHistory(page, 50);
      setEntries(data.entries);
      setPagination(data.pagination);
      // Remove any selected IDs that are no longer present
      setSelectedIds(new Set());
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load history: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory(1);
  }, []);

  const formatDate = (dateStr: string) => {
    if (!dateStr) return "";
    try {
      const d = new Date(dateStr.endsWith("Z") ? dateStr : dateStr + "Z");
      return isNaN(d.getTime()) ? dateStr : d.toLocaleDateString("en-IN", {
        day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const allSelected = entries.length > 0 && entries.every((e) => selectedIds.has(e.id));
  const someSelected = entries.some((e) => selectedIds.has(e.id));

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      const next = new Set(selectedIds);
      entries.forEach((e) => next.add(e.id));
      setSelectedIds(next);
    }
  };

  const handleDelete = async (id: number, url: string) => {
    if (!confirm(`Delete crawl history record #${id} for:\n${url}?`)) return;
    try {
      await deleteCrawlHistoryEntry(id);
      setToast({ type: "success", message: `Deleted history record #${id}.` });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      loadHistory(pagination.page);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to delete: " + (err.response?.data?.detail || err.message) });
    }
  };

  const handleDeleteSelected = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} selected crawl history record${ids.length > 1 ? "s" : ""}?`)) return;

    setDeletingSelected(true);
    try {
      await deleteCrawlHistoryEntries(ids);
      setToast({ type: "success", message: `Deleted ${ids.length} crawl history record${ids.length > 1 ? "s" : ""}.` });
      setSelectedIds(new Set());
      loadHistory(pagination.page);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to delete selected: " + (err.response?.data?.detail || err.message) });
    } finally {
      setDeletingSelected(false);
    }
  };

  const handleClearAll = async () => {
    if (!confirm("Are you sure you want to delete ALL crawl history records? This cannot be undone.")) return;
    try {
      await clearAllCrawlHistory();
      setToast({ type: "success", message: "All crawl history records deleted." });
      setSelectedIds(new Set());
      loadHistory(1);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to clear history: " + (err.response?.data?.detail || err.message) });
    }
  };

  if (loading) {
    return (
      <div className="admin-empty admin-fade-in">
        <div className="admin-empty-icon">⏳</div>
        Loading crawl history…
      </div>
    );
  }

  return (
    <div className="admin-fade-in">
      {toast && (
        <div className={`admin-toast ${toast.type === "success" ? "admin-toast-success" : "admin-toast-error"}`} style={{ marginBottom: "1rem" }}>
          {toast.type === "success" ? "✓" : "✕"} {toast.message}
        </div>
      )}

      <div className="admin-section-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.75rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {entries.length > 0 && (
            <label
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.45rem",
                cursor: "pointer",
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "var(--admin-text-secondary)",
                userSelect: "none",
              }}
              title={allSelected ? "Deselect all" : "Select all visible"}
            >
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected && !allSelected;
                }}
                onChange={toggleSelectAll}
                style={{
                  width: "16px",
                  height: "16px",
                  accentColor: "var(--admin-accent)",
                  cursor: "pointer",
                  borderRadius: "4px",
                }}
              />
              <span>Select All</span>
            </label>
          )}

          <div className="admin-section-title">
            <History size={14} />
            Crawl History ({pagination.total} record{pagination.total === 1 ? "" : "s"})
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          {selectedIds.size > 0 && (
            <button
              id="delete-selected-history-btn"
              className="admin-btn admin-btn-secondary"
              onClick={handleDeleteSelected}
              disabled={deletingSelected}
              style={{
                color: "var(--admin-red)",
                backgroundColor: "var(--admin-red-bg)",
                borderColor: "rgba(239, 68, 68, 0.3)",
                padding: "0.35rem 0.85rem",
                fontSize: "0.78rem",
                fontWeight: 600,
                display: "inline-flex",
                alignItems: "center",
                gap: "0.4rem",
              }}
              title={`Delete ${selectedIds.size} selected items`}
            >
              <Trash2 size={13} />
              {deletingSelected ? "Deleting…" : `Delete Selected (${selectedIds.size})`}
            </button>
          )}

          {pagination.total > 0 && (
            <>
              <button
                id="clear-all-history-btn"
                className="admin-btn admin-btn-secondary"
                onClick={handleClearAll}
                style={{
                  color: "var(--admin-red)",
                  borderColor: "rgba(239, 68, 68, 0.25)",
                  padding: "0.3rem 0.75rem",
                  fontSize: "0.75rem",
                }}
                title="Delete all crawl history records"
              >
                <Trash2 size={12} style={{ marginRight: 4 }} />
                Clear All
              </button>
              <span style={{ fontSize: "0.7rem", color: "var(--admin-text-muted)" }}>
                Page {pagination.page} of {pagination.totalPages}
              </span>
            </>
          )}
        </div>
      </div>

      {entries.length === 0 ? (
        <div className="admin-empty">
          <div className="admin-empty-icon">📋</div>
          No crawl history yet. Submit URLs using the form to start building the knowledge base.
        </div>
      ) : (
        <>
          {entries.map((entry) => {
            const isSuccess = entry.status === "success";
            const isSelected = selectedIds.has(entry.id);

            return (
              <div
                key={entry.id}
                className="admin-card"
                style={{
                  cursor: "default",
                  display: "flex",
                  alignItems: "center",
                  gap: "0.75rem",
                  borderColor: isSelected ? "var(--admin-accent)" : undefined,
                  backgroundColor: isSelected ? "rgba(124, 58, 237, 0.03)" : undefined,
                  boxShadow: isSelected ? "0 0 0 1px var(--admin-accent)" : undefined,
                  transition: "all 0.15s ease",
                }}
              >
                {/* Checkbox / Tick button */}
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    cursor: "pointer",
                    padding: "4px",
                    marginRight: "-2px",
                    flexShrink: 0,
                  }}
                  onClick={(e) => e.stopPropagation()}
                  title={isSelected ? "Deselect" : "Select to delete"}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSelect(entry.id)}
                    style={{
                      width: "17px",
                      height: "17px",
                      accentColor: "var(--admin-accent)",
                      cursor: "pointer",
                      borderRadius: "4px",
                    }}
                  />
                </label>

                <div
                  style={{
                    width: 28,
                    height: 28,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    borderRadius: 8,
                    background: isSuccess ? "var(--admin-green-bg)" : "var(--admin-red-bg)",
                  }}
                >
                  {isSuccess ? (
                    <CheckCircle2 size={15} color="var(--admin-green)" />
                  ) : (
                    <XCircle size={15} color="var(--admin-red)" />
                  )}
                </div>

                <div className="admin-card-info" style={{ flex: 1, minWidth: 0 }}>
                  <div
                    className="admin-card-title"
                    style={{ fontSize: "0.845rem", wordBreak: "break-all" }}
                  >
                    {entry.url}
                  </div>
                  <div className="admin-card-meta">
                    <span className="admin-card-slug">#{entry.id}</span>
                    <span className="admin-card-time">
                      <Clock size={11} />
                      {formatDate(entry.created_at)}
                    </span>
                    {!isSuccess && entry.error_message && (
                      <span
                        style={{
                          fontSize: "0.7rem",
                          color: "var(--admin-red)",
                          fontFamily: "'SF Mono','Fira Code','Cascadia Code',monospace",
                          background: "var(--admin-red-bg)",
                          padding: "0.1rem 0.45rem",
                          borderRadius: 6,
                        }}
                      >
                        {entry.error_message}
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexShrink: 0 }}>
                  <span
                    style={{
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      padding: "0.2rem 0.6rem",
                      borderRadius: 9999,
                      background: isSuccess ? "var(--admin-green-bg)" : "var(--admin-red-bg)",
                      color: isSuccess ? "var(--admin-green)" : "var(--admin-red)",
                    }}
                  >
                    {isSuccess ? "Success" : "Failed"}
                  </span>

                  <button
                    id={`delete-history-${entry.id}`}
                    className="admin-btn admin-btn-secondary admin-btn-icon"
                    onClick={() => handleDelete(entry.id, entry.url)}
                    title={`Delete history record #${entry.id}`}
                    style={{
                      color: "var(--admin-red)",
                      borderColor: "rgba(239, 68, 68, 0.2)",
                      padding: "0.3rem",
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            );
          })}

          {/* Pagination */}
          {pagination.totalPages > 1 && (
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center", marginTop: "1.25rem" }}>
              <button
                className="admin-btn admin-btn-secondary admin-btn-icon"
                onClick={() => loadHistory(pagination.page - 1)}
                disabled={pagination.page <= 1}
              >
                <ChevronLeft size={14} />
              </button>
              <span style={{ fontSize: "0.8rem", color: "var(--admin-text-secondary)", display: "flex", alignItems: "center", padding: "0 0.5rem" }}>
                {pagination.page} / {pagination.totalPages}
              </span>
              <button
                className="admin-btn admin-btn-secondary admin-btn-icon"
                onClick={() => loadHistory(pagination.page + 1)}
                disabled={pagination.page >= pagination.totalPages}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};
