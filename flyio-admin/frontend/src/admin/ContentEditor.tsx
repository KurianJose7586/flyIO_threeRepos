import React, { useState, useEffect } from "react";
import { getPage, getContent, createPage, updatePage, upsertContent } from "./adminApi";
import { ArrowLeft, Save, Loader2, CheckCircle, AlertCircle } from "lucide-react";

type EditorMode = "edit-page" | "create-page" | "edit-content" | "create-content";

interface ContentEditorProps {
  mode: EditorMode;
  identifier?: string;
  onBack: () => void;
}

export const ContentEditor: React.FC<ContentEditorProps> = ({ mode, identifier, onBack }) => {
  const isPage = mode === "edit-page" || mode === "create-page";
  const isCreate = mode === "create-page" || mode === "create-content";

  const [slug, setSlug] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(!isCreate);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    if (isCreate || !identifier) return;

    const load = async () => {
      setLoading(true);
      try {
        if (isPage) {
          const page = await getPage(identifier);
          setSlug(page.slug);
          setTitle(page.title);
          setBody(page.body || "");
        } else {
          const content = await getContent(identifier);
          setSlug(content.key);
          setTitle(content.title || "");
          setBody(content.body || "");
        }
      } catch (err: any) {
        setToast({ type: "error", message: "Failed to load: " + (err.response?.data?.detail || err.message) });
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [identifier, isCreate, isPage]);

  const handleSave = async () => {
    if (isPage && isCreate && !slug.trim()) {
      setToast({ type: "error", message: "Slug is required." });
      return;
    }
    if (!isPage && isCreate && !slug.trim()) {
      setToast({ type: "error", message: "Key is required." });
      return;
    }
    if (isPage && !title.trim()) {
      setToast({ type: "error", message: "Title is required." });
      return;
    }
    if (!body.trim()) {
      setToast({ type: "error", message: "Body content is required." });
      return;
    }

    setSaving(true);
    setToast(null);

    try {
      if (isPage && isCreate) {
        await createPage(slug.trim(), title.trim(), body);
        setToast({ type: "success", message: `Page "${slug}" created successfully!` });
      } else if (isPage && !isCreate) {
        await updatePage(identifier!, { title: title.trim(), body });
        setToast({ type: "success", message: `Page "${identifier}" updated successfully!` });
      } else {
        const key = isCreate ? slug.trim() : identifier!;
        await upsertContent(key, { title: title.trim() || undefined, body });
        setToast({ type: "success", message: `Content "${key}" saved successfully!` });
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || String(err);
      setToast({ type: "error", message: `Save failed: ${detail}` });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="admin-empty admin-fade-in">
        <div className="admin-empty-icon">⏳</div>
        Loading...
      </div>
    );
  }

  const headingText = isCreate
    ? isPage ? "Create New Page" : "Create Content Block"
    : isPage ? `Edit Page` : `Edit Content`;

  return (
    <div className="admin-fade-in">
      {toast && (
        <div className={`admin-toast ${toast.type === "success" ? "admin-toast-success" : "admin-toast-error"}`}>
          {toast.type === "success" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {toast.message}
        </div>
      )}

      <div className="admin-editor">
        {/* Editor Header */}
        <div className="admin-editor-header">
          <button className="admin-btn admin-btn-secondary admin-btn-icon" onClick={onBack} title="Back">
            <ArrowLeft size={16} />
          </button>
          <h2 className="admin-editor-title">{headingText}</h2>
          {!isCreate && identifier && (
            <span className="admin-card-slug" style={{ marginLeft: "auto" }}>
              {isPage ? `/${identifier}` : identifier}
            </span>
          )}
        </div>

        {/* Slug / Key field */}
        <div className="admin-field">
          <label className="admin-field-label">
            {isPage ? "Slug" : "Key"}
          </label>
          {isCreate ? (
            <input
              className="admin-input"
              type="text"
              placeholder={isPage ? "e.g. privacy-policy" : "e.g. footer-text"}
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, ""))}
              disabled={saving}
            />
          ) : (
            <div className="admin-input-readonly">{identifier}</div>
          )}
        </div>

        {/* Title field */}
        <div className="admin-field">
          <label className="admin-field-label">
            Title {!isPage && <span className="optional">(optional)</span>}
          </label>
          <input
            className="admin-input"
            type="text"
            placeholder={isPage ? "Page title" : "Display title (optional)"}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={saving}
          />
        </div>

        {/* Body field */}
        <div className="admin-field">
          <label className="admin-field-label">Body Content</label>
          <textarea
            className="admin-textarea"
            placeholder="Enter content here... HTML and plain text are both supported."
            value={body}
            onChange={(e) => setBody(e.target.value)}
            disabled={saving}
          />
        </div>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "0.75rem", paddingTop: "0.5rem" }}>
          <button
            className="admin-btn admin-btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saving ? "Saving..." : "Save Changes"}
          </button>
          <button
            className="admin-btn admin-btn-secondary"
            onClick={onBack}
            disabled={saving}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};
