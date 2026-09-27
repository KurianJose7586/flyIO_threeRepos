import React, { useState, useEffect } from "react";
import { getCategories, createCategory, updateCategory, deleteCategory } from "./adminApi";
import type { Category } from "./adminApi";
import { Plus, Pencil, Trash2, Check, X, ArrowLeft } from "lucide-react";

interface AdminBlogCategoriesProps {
  onBack: () => void;
}

export const AdminBlogCategories: React.FC<AdminBlogCategoriesProps> = ({ onBack }) => {
  const [categories, setCategories] = useState<Category[]>([]);
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

  const fetchCategories = async () => {
    try {
      setLoading(true);
      const data = await getCategories();
      setCategories(data);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load categories: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchCategories(); }, []);

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
      setToast({ type: "error", message: "Category name is required." });
      return;
    }
    try {
      await createCategory({ name: finalName, slug: finalSlug });
      setToast({ type: "success", message: `Category '${finalName}' created.` });
      setNewName("");
      setNewSlug("");
      setSlugCustomized(false);
      setShowCreate(false);
      fetchCategories();
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
      await updateCategory(id, { name: editName.trim(), slug: editSlug.trim() });
      setToast({ type: "success", message: `Category #${id} updated.` });
      setEditingId(null);
      fetchCategories();
    } catch (err: any) {
      setToast({ type: "error", message: err.response?.data?.detail || err.message });
    }
  };

  const handleDelete = async (id: number, name: string) => {
    if (!confirm(`Delete category "${name}"? Posts using it will have their category cleared.`)) return;
    try {
      await deleteCategory(id);
      setToast({ type: "success", message: `Category '${name}' deleted.` });
      fetchCategories();
    } catch (err: any) {
      setToast({ type: "error", message: err.response?.data?.detail || err.message });
    }
  };

  const startEdit = (cat: Category) => {
    setEditingId(cat.id);
    setEditName(cat.name);
    setEditSlug(cat.slug);
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
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>Manage Categories</h2>
        <button className="admin-btn admin-btn-create" onClick={() => setShowCreate(!showCreate)}>
          <Plus size={14} /> Add Category
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
              placeholder="e.g. Travel Tips"
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
              placeholder="e.g. travel-tips"
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
          Loading categories...
        </div>
      ) : categories.length === 0 ? (
        <div className="admin-empty admin-fade-in">
          <div className="admin-empty-icon">📂</div>
          <p>No categories yet. Create one above.</p>
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
              {categories.map((cat) => (
                <tr key={cat.id} style={{ borderBottom: "1px solid var(--admin-border)" }}>
                  {editingId === cat.id ? (
                    <>
                      <td style={{ padding: "0.5rem 1rem" }}>
                        <input className="admin-input" value={editName} onChange={(e) => setEditName(e.target.value)} style={{ fontSize: "0.85rem" }} />
                      </td>
                      <td style={{ padding: "0.5rem 1rem" }}>
                        <input className="admin-input" value={editSlug} onChange={(e) => setEditSlug(e.target.value)} style={{ fontSize: "0.85rem" }} />
                      </td>
                      <td style={{ padding: "0.5rem 1rem", textAlign: "right" }}>
                        <div style={{ display: "flex", gap: "0.25rem", justifyContent: "flex-end" }}>
                          <button className="admin-btn admin-btn-create" onClick={() => handleUpdate(cat.id)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
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
                      <td style={{ padding: "0.75rem 1rem" }}>{cat.name}</td>
                      <td style={{ padding: "0.75rem 1rem", color: "var(--admin-text-secondary)" }}>{cat.slug}</td>
                      <td style={{ padding: "0.75rem 1rem", textAlign: "right" }}>
                        <div style={{ display: "flex", gap: "0.25rem", justifyContent: "flex-end" }}>
                          <button className="admin-btn admin-btn-secondary" onClick={() => startEdit(cat)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
                            <Pencil size={12} />
                          </button>
                          <button className="admin-btn admin-btn-danger" onClick={() => handleDelete(cat.id, cat.name)} style={{ padding: "0.3rem 0.5rem", fontSize: "0.75rem" }}>
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
