import React, { useState, useEffect } from "react";
import {
  getAdminBlogPost,
  createBlogPost,
  updateBlogPost,
  getCategories,
  getTags,
  uploadBlogBanner,
  Category,
  Tag,
} from "./adminApi";
import { CKEditorField } from "./CKEditorField";
import { ArrowLeft, Save, Upload, Image as ImageIcon } from "lucide-react";

interface AdminBlogEditorProps {
  postId?: number; // if set, edit mode; if undefined, create mode
  onBack: () => void;
}

export const AdminBlogEditor: React.FC<AdminBlogEditorProps> = ({ postId, onBack }) => {
  const isEdit = Boolean(postId);

  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [summary, setSummary] = useState("");
  const [author, setAuthor] = useState("");
  const [banner, setBanner] = useState("");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [body, setBody] = useState("");
  const [metaTitle, setMetaTitle] = useState("");
  const [metaDescription, setMetaDescription] = useState("");
  const [publish, setPublish] = useState(false);
  const [slugCustomized, setSlugCustomized] = useState(false);

  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingBanner, setUploadingBanner] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  // Helper to slugify title
  const generateSlug = (text: string) => {
    return text
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/[\s_-]+/g, "-")
      .replace(/^-+|-+$/g, "");
  };

  useEffect(() => {
    // Load categories and tags in parallel with post data if in edit mode
    Promise.all([
      getCategories(),
      getTags(),
      isEdit && postId ? getAdminBlogPost(postId) : Promise.resolve(null),
    ])
      .then(([cats, tagList, post]) => {
        setCategories(cats);
        setTags(tagList);

        if (post) {
          setTitle(post.title || "");
          setSlug(post.slug || "");
          setSlugCustomized(true);
          setSummary(post.summary || "");
          setAuthor(post.author || "");
          setBanner(post.banner || "");
          setCategoryId(post.category_id || "");
          setSelectedTagIds(post.tag_ids || []);
          setBody(post.body || "");
          setMetaTitle(post.meta_title || "");
          setMetaDescription(post.meta_description || "");
          setPublish(Boolean(post.published_at));
        }
      })
      .catch((err) => {
        setToast({ type: "error", message: "Failed to load data: " + (err.message || String(err)) });
      })
      .finally(() => setLoading(false));
  }, [postId, isEdit]);

  const handleTitleChange = (val: string) => {
    setTitle(val);
    if (!isEdit && !slugCustomized) {
      setSlug(generateSlug(val));
    }
  };

  const handleRegenerateSlug = () => {
    setSlug(generateSlug(title));
    setSlugCustomized(false);
  };

  const handleBannerUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setUploadingBanner(true);
      const url = await uploadBlogBanner(file);
      setBanner(url);
      setToast({ type: "success", message: "Banner image uploaded successfully." });
    } catch (err: any) {
      setToast({
        type: "error",
        message: "Banner upload failed: " + (err.response?.data?.detail || err.message),
      });
    } finally {
      setUploadingBanner(false);
    }
  };

  const toggleTag = (tagId: number) => {
    setSelectedTagIds((prev) =>
      prev.includes(tagId) ? prev.filter((id) => id !== tagId) : [...prev, tagId]
    );
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !slug.trim() || !body.trim()) {
      setToast({ type: "error", message: "Title, Slug, and Body are required." });
      return;
    }

    setSaving(true);
    setToast(null);

    const payload = {
      title,
      slug,
      summary,
      author,
      banner,
      category_id: categoryId === "" ? null : Number(categoryId),
      tag_ids: selectedTagIds,
      body,
      meta_title: metaTitle,
      meta_description: metaDescription,
      publish,
    };

    try {
      if (isEdit && postId) {
        await updateBlogPost(postId, payload);
        setToast({ type: "success", message: "Blog post updated successfully." });
      } else {
        await createBlogPost(payload);
        setToast({ type: "success", message: "Blog post created successfully." });
        setTimeout(() => onBack(), 800);
      }
    } catch (err: any) {
      setToast({ type: "error", message: "Save failed: " + (err.response?.data?.detail || err.message) });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="admin-empty admin-fade-in">
        <div className="admin-empty-icon">⏳</div>
        Loading editor...
      </div>
    );
  }

  return (
    <div className="admin-fade-in" style={{ maxWidth: "850px", margin: "0 auto" }}>
      {toast && (
        <div className={`admin-toast ${toast.type === "success" ? "admin-toast-success" : "admin-toast-error"}`}>
          {toast.type === "success" ? "✓" : "✕"} {toast.message}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem" }}>
        <button className="admin-btn admin-btn-secondary" onClick={onBack}>
          <ArrowLeft size={14} />
          Back to List
        </button>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>
          {isEdit ? `Edit Blog Post #${postId}` : "Create New Blog Post"}
        </h2>
      </div>

      <form onSubmit={handleSave} className="admin-form-card">
        <div className="admin-form-group">
          <label className="admin-form-label">Post Title *</label>
          <input
            type="text"
            className="admin-input"
            value={title}
            onChange={(e) => handleTitleChange(e.target.value)}
            placeholder="e.g. 10 Best Places to Visit in Goa in 2026"
            required
          />
        </div>

        <div className="admin-form-group">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label className="admin-form-label">URL Slug *</label>
            {title && (
              <button
                type="button"
                onClick={handleRegenerateSlug}
                className="admin-btn admin-btn-secondary"
                style={{ padding: "0.15rem 0.5rem", fontSize: "0.7rem", marginBottom: "0.25rem" }}
                title="Regenerate slug from title"
              >
                ↺ Auto-generate
              </button>
            )}
          </div>
          <input
            type="text"
            className="admin-input"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value.toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-"));
              setSlugCustomized(true);
            }}
            placeholder="e.g. 10-best-places-goa-2026"
            required
          />
          <span style={{ fontSize: "0.75rem", color: "var(--admin-text-secondary)", marginTop: "0.25rem", display: "block" }}>
            Live URL preview: <code>/blog/{slug || "your-slug"}</code>
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div className="admin-form-group">
            <label className="admin-form-label">Author Name</label>
            <input
              type="text"
              className="admin-input"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="e.g. Jane Doe, Travel Editor"
            />
          </div>

          <div className="admin-form-group">
            <label className="admin-form-label">Category</label>
            <select
              className="admin-input"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value === "" ? "" : Number(e.target.value))}
            >
              <option value="">-- No Category --</option>
              {categories.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="admin-form-group">
          <label className="admin-form-label">Post Summary</label>
          <textarea
            className="admin-textarea"
            rows={3}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="Brief overview or teaser for the blog card / header..."
          />
        </div>

        {/* Tags Selector */}
        <div className="admin-form-group">
          <label className="admin-form-label">Tags</label>
          {tags.length === 0 ? (
            <span style={{ fontSize: "0.8rem", color: "var(--admin-text-secondary)" }}>
              No tags available. You can add tags in the Tags manager.
            </span>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.25rem" }}>
              {tags.map((tag) => {
                const isSelected = selectedTagIds.includes(tag.id);
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => toggleTag(tag.id)}
                    style={{
                      padding: "0.3rem 0.75rem",
                      borderRadius: "16px",
                      fontSize: "0.8rem",
                      fontWeight: 500,
                      cursor: "pointer",
                      border: isSelected ? "1px solid var(--admin-accent)" : "1px solid var(--admin-border)",
                      background: isSelected ? "var(--admin-accent-bg, #7C3AED20)" : "transparent",
                      color: isSelected ? "var(--admin-accent)" : "var(--admin-text-secondary)",
                      transition: "all 0.15s ease",
                    }}
                  >
                    {isSelected ? `✓ ${tag.name}` : `+ ${tag.name}`}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Banner Image Upload & Preview */}
        <div className="admin-form-group">
          <label className="admin-form-label">Featured Banner Image</label>
          <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
            <input
              type="text"
              className="admin-input"
              value={banner}
              onChange={(e) => setBanner(e.target.value)}
              placeholder="Image URL or upload a file ->"
              style={{ flex: 1 }}
            />
            <label
              className="admin-btn admin-btn-secondary"
              style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem", cursor: "pointer", margin: 0 }}
            >
              <Upload size={14} />
              {uploadingBanner ? "Uploading..." : "Upload Image"}
              <input
                type="file"
                accept="image/*"
                onChange={handleBannerUpload}
                disabled={uploadingBanner}
                style={{ display: "none" }}
              />
            </label>
          </div>
          {banner && (
            <div style={{ marginTop: "0.75rem", border: "1px solid var(--admin-border)", borderRadius: "8px", overflow: "hidden", maxWidth: "300px" }}>
              <img
                src={banner}
                alt="Banner preview"
                style={{ width: "100%", height: "140px", objectFit: "cover", display: "block" }}
                onError={(e) => {
                  (e.target as HTMLElement).style.display = "none";
                }}
              />
            </div>
          )}
        </div>

        {/* Article Body using CKEditor */}
        <div className="admin-form-group">
          <label className="admin-form-label">Article Body (Rich Text) *</label>
          <CKEditorField value={body} onChange={setBody} />
        </div>

        <div style={{ borderTop: "1px solid var(--admin-border)", paddingTop: "1.25rem", marginTop: "1.5rem" }}>
          <h3 style={{ fontSize: "0.95rem", fontWeight: 600, marginBottom: "1rem", color: "var(--admin-accent)" }}>
            SEO Plumbing & Search Engine Metadata
          </h3>

          <div className="admin-form-group">
            <label className="admin-form-label">Meta Title (SEO Title)</label>
            <input
              type="text"
              className="admin-input"
              value={metaTitle}
              onChange={(e) => setMetaTitle(e.target.value)}
              placeholder="e.g. Top 10 Places to Visit in Goa | Travel Guide"
            />
          </div>

          <div className="admin-form-group">
            <label className="admin-form-label">Meta Description (SEO Snippet)</label>
            <textarea
              className="admin-textarea"
              rows={3}
              value={metaDescription}
              onChange={(e) => setMetaDescription(e.target.value)}
              placeholder="Brief summary for search engine snippet..."
            />
          </div>
        </div>

        <div style={{ borderTop: "1px solid var(--admin-border)", paddingTop: "1.25rem", marginTop: "1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={publish}
              onChange={(e) => setPublish(e.target.checked)}
              style={{ width: "18px", height: "18px", accentColor: "var(--admin-accent)" }}
            />
            <span>Publish Post Immediately</span>
          </label>

          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button type="button" className="admin-btn admin-btn-secondary" onClick={onBack}>
              Cancel
            </button>
            <button type="submit" className="admin-btn admin-btn-create" disabled={saving}>
              <Save size={14} />
              {saving ? "Saving..." : isEdit ? "Update Post" : "Save Post"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};
