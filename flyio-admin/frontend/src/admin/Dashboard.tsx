import React, { useState, useEffect } from "react";
import { getPages, getContentList, deletePage } from "./adminApi";
import type { CmsPage, CmsContent } from "./adminApi";
import { FileText, Layout, Plus, Edit3, Trash2, Clock, ChevronRight, Database } from "lucide-react";

interface DashboardProps {
  onEditPage: (slug: string) => void;
  onEditContent: (key: string) => void;
  onCreatePage: () => void;
  onCreateContent: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({
  onEditPage,
  onEditContent,
  onCreatePage,
  onCreateContent,
}) => {
  const [pages, setPages] = useState<CmsPage[]>([]);
  const [content, setContent] = useState<CmsContent[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const [p, c] = await Promise.all([getPages(), getContentList()]);
      setPages(p);
      setContent(c);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load data: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleDelete = async (slug: string) => {
    if (!confirm(`Delete page "${slug}"? This cannot be undone.`)) return;
    try {
      await deletePage(slug);
      setToast({ type: "success", message: `Page "${slug}" deleted.` });
      loadData();
    } catch (err: any) {
      setToast({ type: "error", message: "Delete failed: " + (err.response?.data?.detail || err.message) });
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr + "Z");
      return d.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div className="admin-empty admin-fade-in">
        <div className="admin-empty-icon">⏳</div>
        Loading CMS data...
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

      {/* ── Stats Row ─────────────────────────────────────────────────────── */}
      <div className="admin-stats">
        <div className="admin-stat-card">
          <div className="admin-stat-value">{pages.length}</div>
          <div className="admin-stat-label">
            <FileText size={11} style={{ display: "inline", marginRight: "0.3rem", verticalAlign: "-1px" }} />
            Pages
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-value">{content.length}</div>
          <div className="admin-stat-label">
            <Layout size={11} style={{ display: "inline", marginRight: "0.3rem", verticalAlign: "-1px" }} />
            Content Blocks
          </div>
        </div>
        <div className="admin-stat-card">
          <div className="admin-stat-value">{pages.length + content.length}</div>
          <div className="admin-stat-label">
            <Database size={11} style={{ display: "inline", marginRight: "0.3rem", verticalAlign: "-1px" }} />
            Total Entries
          </div>
        </div>
      </div>

      {/* ── Pages Section ─────────────────────────────────────────────────── */}
      <div style={{ marginBottom: "2.5rem" }}>
        <div className="admin-section-header">
          <div className="admin-section-title">
            <FileText size={14} />
            Pages ({pages.length})
          </div>
          <button className="admin-btn admin-btn-create" onClick={onCreatePage}>
            <Plus size={14} />
            New Page
          </button>
        </div>

        {pages.length === 0 ? (
          <div className="admin-empty">
            <div className="admin-empty-icon">📄</div>
            No pages yet. Create your first page — privacy policy, terms & conditions, about us.
          </div>
        ) : (
          pages.map((page) => (
            <div key={page.slug} className="admin-card">
              <div className="admin-card-info" onClick={() => onEditPage(page.slug)}>
                <div className="admin-card-title">{page.title}</div>
                <div className="admin-card-meta">
                  <span className="admin-card-slug">/{page.slug}</span>
                  <span className="admin-card-time">
                    <Clock size={11} />
                    {formatDate(page.updated_at)}
                  </span>
                </div>
              </div>
              <div className="admin-card-actions">
                <button
                  className="admin-btn admin-btn-secondary admin-btn-icon"
                  onClick={() => onEditPage(page.slug)}
                  title="Edit"
                >
                  <Edit3 size={14} />
                </button>
                <button
                  className="admin-btn admin-btn-danger admin-btn-icon"
                  onClick={() => handleDelete(page.slug)}
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* ── Site Content Section ───────────────────────────────────────────── */}
      <div>
        <div className="admin-section-header">
          <div className="admin-section-title">
            <Layout size={14} />
            Site Content ({content.length})
          </div>
          <button className="admin-btn admin-btn-create" onClick={onCreateContent}>
            <Plus size={14} />
            New Content Block
          </button>
        </div>

        {content.length === 0 ? (
          <div className="admin-empty">
            <div className="admin-empty-icon">📋</div>
            No content blocks yet. Create blocks for footer text, company info, contact details.
          </div>
        ) : (
          content.map((item) => (
            <div key={item.key} className="admin-card" onClick={() => onEditContent(item.key)}>
              <div className="admin-card-info">
                <div className="admin-card-title">{item.title || item.key}</div>
                <div className="admin-card-meta">
                  <span className="admin-card-slug">{item.key}</span>
                  <span className="admin-card-time">
                    <Clock size={11} />
                    {formatDate(item.updated_at)}
                  </span>
                </div>
              </div>
              <ChevronRight size={16} style={{ color: "rgba(255,255,255,0.15)", flexShrink: 0 }} />
            </div>
          ))
        )}
      </div>
    </div>
  );
};
