import React, { useState, useEffect } from "react";
import { getTags, createTag, updateTag, deleteTag } from "./adminApi";
import type { Tag } from "./adminApi";
import { Plus, Pencil, Trash2, Check, X, ArrowLeft } from "lucide-react";

interface AdminBlogTagsProps {
  onBack: () => void;
}

export const AdminBlogTags: React.FC<AdminBlogTagsProps> = ({ onBack }) => {
  const [tags, setTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Inline create
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [slugCustomized, setSlugCustomized] = useState(false);

  // Inline edit
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editSlug, setEditSlug] = useState("");

  const fetchTags = async () => {
    try {
      setLoading(true);
      const data = await getTags();
      setTags(data);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load tags: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchTags(); }, []);

  const generateSlug = (text: string) =>
    text.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-").replace(/^-+|-+$/g, "");

  const handleNameChange = (val: string) => {
    setNewName(val);
    if (!slugCustomized) {
      setNewSlug(generateSlug(val));
    }
  };

  const handleCreate = async () => {
    const finalName = newName.trim();
    const finalSlug = (newSlug.trim() || generateSlug(finalName));

    if (!finalName || !finalSlug) {
      setToast({ type: "error", message: "Tag name is required." });
      return;
    }
    try {
      await createTag({ name: finalName, slug: finalSlug });
      setToast({ type: "success", message: `Tag '${finalName}' created.` });
      setNewName("");
      setNewSlug("");
      setSlugCustomized(false);
      setShowCreate(false);
      fetchTags();
    } catch (err: any) {
      setToast({ type: "error", message: err.response?.data?.detail || err.message });
    }
  };

  const handleUpdate = async (id: number) => {
    if (!editName.trim() || !editSlug.trim()) {
      setToast({ type: "error", message: "Name and slug are required." });
      return;
    }
    try {
      await updateTag(id, { name: editName.trim(), slug: editSlug.trim() });
      setToast({ type: "success", message: `Tag #${id} updated.` });
      setEditingId(null);
      fetchTags();
    } catch (err: any) {
      setToast({ type: "error", message: err.response?.data?.detail || err.message });
    }
  };

  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete tag "${name}"? It will be removed from all posts.`)) return;
    try {
      await deleteTag(id);
      setToast({ type: "success", message: `Tag '${name}' deleted.` });
      fetchTags();
    } catch (err: any) {
      setToast({ type: "error", message: err.response?.data?.detail || err.message });
    }
  };

  const startEdit = (tag: Tag) => {
    setEditingId(tag.id);
    setEditName(tag.name);
    setEditSlug(tag.slug);
  };

  return (
    <div className="admin-fade-in" style={{ maxWidth: "700px", margin: "0 auto" }}>
      {toast && (
        <div className={`admin-toast ${toast.type === "success" ? "admin-toast-success" : "admin-toast-error"}`}>
          {toast.type === "success" ? "✓" : "✕"} {toast.message}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem" }}>
        <button className="admin-btn admin-btn-secondary" onClick={onBack}>
          <ArrowLeft size={14} /> Back to Blog
        </button>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>Manage Tags</h2>
        <button className="admin-btn admin-btn-create" onClick={() => setShowCreate(!showCreate)}>
          <Plus size={14} /> Add Tag
        </button>
      </div>

      {showCreate && (
        <div className="admin-form-card" style={{ marginBottom: "1rem", padding: "1rem", display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <label className="admin-form-label" style={{ fontSize: "0.75rem" }}>Name</label>
            <input
              className="admin-input"
              value={newName}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="e.g. Budget Travel"
            />
          </div>
          <div style={{ flex: 1 }}>
            <label className="admin-form-label" style={{ fontSize: "0.75rem" }}>Slug</label>
            <input
              className="admin-input"
              value={newSlug}
              onChange={(e) => {
                setNewSlug(e.target.value.toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-"));
                setSlugCustomized(true);
              }}
              placeholder="e.g. budget-travel"
            />
          </div>
          <button className="admin-btn admin-btn-create" onClick={handleCreate} style={{ padding: "0.5rem" }}>
            <Check size={14} />
          </button>
          <button className="admin-btn admin-btn-secondary" onClick={() => { setShowCreate(false); setNewName(""); setNewSlug(""); }} style={{ padding: "0.5rem" }}>
            <X size={14} />
          </button>
        </div>
      )}

      {loading ? (
        <div className="admin-empty admin-fade-in">
          <div className="admin-empty-icon">⏳</div>
          Loading tags...
        </div>
      ) : tags.length === 0 ? (
        <div className="admin-empty admin-fade-in">
          <div className="admin-empty-icon">🏷️</div>
          <p>No tags yet. Create one above.</p>
        </div>
      ) : (
        <div className="admin-form-card" style={{ padding: 0 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--admin-border)" }}>
                <th style={{ textAlign: "left", padding: "0.75rem 1rem", fontWeight: 600 }}>Name</th>
                <th style={{ textAlign: "left", padding: "0.75rem 1rem", fontWeight: 600 }}>Slug</th>
                <th style={{ textAlign: "right", padding: "0.75rem 1rem", fontWeight: 600 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {tags.map((tag) => (
                <tr key={tag.id} style={{ borderBottom: "1px solid var(--admin-border)" }}>
                  {editingId === tag.id ? (
                    <>
                      <td style={{ padding: "0.5rem 1rem" }}>
                        <input className="admin-input" value={editName} onChange={(e) => setEditName(e.target.value)} style={{ fontSize: "0.85rem" }} />
                      </td>
                      <td style={{ padding: "0.5rem 1rem" }}>
                        <input className="admin-input" value={editSlug} onChange={(e) => setEditSlug(e.target.value)} style={{ fontSize: "0.85rem" }} />
                      </td>
                      <td style={{ padding: "0.5rem 1rem", textAlign: "right" }}>
                        <div style={{ display: "flex", gap: "0.25rem", justifyContent: "flex-end" }}>
                          <button className="admin-btn admin-btn-create" onClick={() => handleUpdate(tag.id)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
                            <Check size={12} />
                          </button>
                          <button className="admin-btn admin-btn-secondary" onClick={() => setEditingId(null)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
                            <X size={12} />
                          </button>
                        </div>
                      </td>
                    </>
                  ) : (
                    <>
                      <td style={{ padding: "0.75rem 1rem" }}>{tag.name}</td>
                      <td style={{ padding: "0.75rem 1rem", color: "var(--admin-text-secondary)" }}>{tag.slug}</td>
                      <td style={{ padding: "0.75rem 1rem", textAlign: "right" }}>
                        <div style={{ display: "flex", gap: "0.25rem", justifyContent: "flex-end" }}>
                          <button className="admin-btn admin-btn-secondary" onClick={() => startEdit(tag)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
                            <Pencil size={12} />
                          </button>
                          <button className="admin-btn admin-btn-danger" onClick={() => handleDelete(tag.id, tag.name)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
