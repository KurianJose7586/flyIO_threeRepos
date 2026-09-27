import React, { useState, useEffect } from "react";
import { getAdminBlogPosts, deleteBlogPost } from "./adminApi";
import type { BlogPost } from "./adminApi";
import { BookOpen, Plus, Edit3, Trash2, Clock, Globe, Folder, Tag as TagIcon } from "lucide-react";

interface AdminBlogListProps {
  onEditBlog: (id: number) => void;
  onCreateBlog: () => void;
  onManageCategories?: () => void;
  onManageTags?: () => void;
}

export const AdminBlogList: React.FC<AdminBlogListProps> = ({
  onEditBlog,
  onCreateBlog,
  onManageCategories,
  onManageTags,
}) => {
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const loadPosts = async () => {
    setLoading(true);
    try {
      const data = await getAdminBlogPosts();
      setPosts(data);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load blog posts: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPosts();
  }, []);

  const handleDelete = async (id: number, title: string) => {
    if (!confirm(`Delete blog post "${title}"? This cannot be undone.`)) return;
    try {
      await deleteBlogPost(id);
      setToast({ type: "success", message: `Post "${title}" deleted.` });
      loadPosts();
    } catch (err: any) {
      setToast({ type: "error", message: "Delete failed: " + (err.response?.data?.detail || err.message) });
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  if (loading) {
    return (
      <div className="admin-empty admin-fade-in">
        <div className="admin-empty-icon">⏳</div>
        Loading blog posts...
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
          <BookOpen size={16} />
          Blog Posts ({posts.length})
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {onManageCategories && (
            <button className="admin-btn admin-btn-secondary" onClick={onManageCategories}>
              <Folder size={14} />
              Categories
            </button>
          )}
          {onManageTags && (
            <button className="admin-btn admin-btn-secondary" onClick={onManageTags}>
              <TagIcon size={14} />
              Tags
            </button>
          )}
          <button className="admin-btn admin-btn-create" onClick={onCreateBlog}>
            <Plus size={14} />
            New Post
          </button>
        </div>
      </div>

      {posts.length === 0 ? (
        <div className="admin-empty">
          <div className="admin-empty-icon">✍️</div>
          No blog posts created yet. Click "New Post" to author your first article.
        </div>
      ) : (
        posts.map((post) => {
          const isPublished = Boolean(post.published_at);
          return (
            <div key={post.id} className="admin-card">
              <div className="admin-card-info" onClick={() => onEditBlog(post.id)}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <div className="admin-card-title">{post.title}</div>
                  <span
                    style={{
                      fontSize: "0.65rem",
                      fontWeight: 600,
                      padding: "0.15rem 0.45rem",
                      borderRadius: "12px",
                      background: isPublished ? "var(--admin-green-bg)" : "var(--admin-accent-bg)",
                      color: isPublished ? "var(--admin-green)" : "var(--admin-accent)",
                    }}
                  >
                    {isPublished ? "Published" : "Draft"}
                  </span>
                </div>
                <div className="admin-card-meta">
                  <span className="admin-card-slug">/blog/{post.slug}</span>
                  <span className="admin-card-time">
                    <Clock size={11} />
                    {isPublished ? `Published ${formatDate(post.published_at!)}` : `Updated ${formatDate(post.updated_at)}`}
                  </span>
                </div>
              </div>

              <div className="admin-card-actions">
                {isPublished && (
                  <a
                    href={`/blog/${post.slug}`}
                    target="_blank"
                    rel="noreferrer"
                    className="admin-btn admin-btn-secondary admin-btn-icon"
                    title="Preview Live"
                  >
                    <Globe size={14} />
                  </a>
                )}
                <button
                  className="admin-btn admin-btn-secondary admin-btn-icon"
                  onClick={() => onEditBlog(post.id)}
                  title="Edit"
                >
                  <Edit3 size={14} />
                </button>
                <button
                  className="admin-btn admin-btn-danger admin-btn-icon"
                  onClick={() => handleDelete(post.id, post.title)}
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
};
