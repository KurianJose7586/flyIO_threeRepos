import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getPublicBlogPosts } from "../services/api";
import type { PublicBlogPost } from "../services/api";
import {
  BookOpen,
  Calendar,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  ArrowLeft,
  User,
  Folder,
  Tag as TagIcon,
  ArrowUpDown,
} from "lucide-react";

export const BlogListPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const pageParam = parseInt(searchParams.get("page") || "1", 10);
  const sortParam = searchParams.get("sort") || "created_at";
  const orderParam = searchParams.get("order") || "desc";

  const [posts, setPosts] = useState<PublicBlogPost[]>([]);
  const [pagination, setPagination] = useState({ page: 1, limit: 10, total: 0, totalPages: 1 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");

    getPublicBlogPosts(pageParam, 10, sortParam, orderParam)
      .then((data) => {
        if (data.success) {
          setPosts(data.posts);
          setPagination(data.pagination);
        } else {
          setError("Failed to load blog posts.");
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load blog posts.");
      })
      .finally(() => setLoading(false));
  }, [pageParam, sortParam, orderParam]);

  const handleSortChange = (newSort: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("sort", newSort);
    params.set("page", "1");
    setSearchParams(params);
  };

  const handleOrderChange = (newOrder: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("order", newOrder);
    params.set("page", "1");
    setSearchParams(params);
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

  return (
    <div className="min-h-screen bg-[#FAFAF9] text-[#111114]">
      {/* Header Bar */}
      <header className="border-b border-[#E8E7E3] bg-white sticky top-0 z-40">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <Link to="/" className="inline-flex items-center gap-2 text-sm font-semibold text-[#6B6B72] hover:text-[#111114] transition-colors">
            <ArrowLeft size={16} />
            <span>Back to Flyio.ai</span>
          </Link>
          <div className="inline-flex items-center gap-2 text-sm font-bold text-[#7C3AED]">
            <BookOpen size={16} />
            <span>Travel Blog</span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 py-12 md:py-16">
        <div className="text-center mb-10 space-y-3">
          <h1 className="text-3xl md:text-5xl font-extrabold text-[#111114] tracking-tight">
            Travel Guides & Insights
          </h1>
          <p className="text-base text-[#6B6B72] max-w-xl mx-auto">
            Discover curated itineraries, destination guides, and travel tips published weekly.
          </p>
        </div>

        {/* Filter & Sort Controls */}
        <div className="flex items-center justify-between mb-8 pb-4 border-b border-[#E8E7E3]">
          <div className="text-xs font-semibold text-[#6B6B72]">
            {pagination.total} {pagination.total === 1 ? "article" : "articles"} published
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-xs text-[#6B6B72] font-medium">
              <ArrowUpDown size={13} />
              <span>Sort:</span>
            </div>
            <select
              value={sortParam}
              onChange={(e) => handleSortChange(e.target.value)}
              className="text-xs font-medium bg-white border border-[#E8E7E3] rounded-lg px-2.5 py-1.5 text-[#111114] focus:outline-none focus:border-[#7C3AED]"
            >
              <option value="created_at">Date</option>
              <option value="author">Author</option>
            </select>

            <select
              value={orderParam}
              onChange={(e) => handleOrderChange(e.target.value)}
              className="text-xs font-medium bg-white border border-[#E8E7E3] rounded-lg px-2.5 py-1.5 text-[#111114] focus:outline-none focus:border-[#7C3AED]"
            >
              <option value="desc">Newest / Z-A</option>
              <option value="asc">Oldest / A-Z</option>
            </select>
          </div>
        </div>

        {loading ? (
          <div className="min-h-[300px] flex items-center justify-center p-6 text-[#6B6B72]">
            <div className="text-center space-y-3">
              <div className="text-3xl animate-bounce">✍️</div>
              <p className="text-sm font-medium">Loading articles...</p>
            </div>
          </div>
        ) : error ? (
          <div className="bg-white border border-[#E8E7E3] rounded-2xl p-8 text-center text-red-500 max-w-md mx-auto">
            {error}
          </div>
        ) : posts.length === 0 ? (
          <div className="bg-white border border-[#E8E7E3] rounded-2xl p-12 text-center space-y-3 max-w-md mx-auto">
            <div className="text-4xl">📚</div>
            <h3 className="text-lg font-bold text-[#111114]">No Blog Posts Yet</h3>
            <p className="text-sm text-[#6B6B72]">Check back soon for new articles!</p>
          </div>
        ) : (
          <div className="space-y-6">
            {posts.map((post) => (
              <article
                key={post.id}
                className="bg-white border border-[#E8E7E3] hover:border-[#7C3AED] rounded-2xl overflow-hidden transition-all duration-200 shadow-xs hover:shadow-md group flex flex-col md:flex-row"
              >
                {post.banner && (
                  <div className="md:w-56 h-48 md:h-auto shrink-0 bg-gray-100 overflow-hidden">
                    <img
                      src={post.banner}
                      alt={post.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  </div>
                )}

                <div className="p-6 md:p-8 flex-1 space-y-3 flex flex-col justify-between">
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2.5 text-xs text-[#6B6B72]">
                      {post.category_name && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#7C3AED15] text-[#7C3AED] font-semibold text-[11px]">
                          <Folder size={11} />
                          {post.category_name}
                        </span>
                      )}
                      {post.author && (
                        <span className="inline-flex items-center gap-1 font-medium text-[#111114]">
                          <User size={11} className="text-[#7C3AED]" />
                          {post.author}
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1 font-medium">
                        <Calendar size={12} className="text-[#7C3AED]" />
                        {formatDate(post.published_at)}
                      </span>
                    </div>

                    <h2 className="text-xl md:text-2xl font-bold text-[#111114] group-hover:text-[#7C3AED] transition-colors">
                      <Link to={`/blog/${post.slug}`}>{post.title}</Link>
                    </h2>

                    <p className="text-sm text-[#6B6B72] line-clamp-3 leading-relaxed">
                      {post.summary || post.meta_description || "Read more about this article..."}
                    </p>

                    {post.tags && post.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {post.tags.map((tag) => (
                          <span
                            key={tag.id}
                            className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-md bg-[#F4F4F5] text-[#6B6B72]"
                          >
                            <TagIcon size={9} />
                            {tag.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="pt-2">
                    <Link
                      to={`/blog/${post.slug}`}
                      className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#7C3AED] hover:text-[#6D28D9] transition-colors"
                    >
                      <span>Read Article</span>
                      <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
                    </Link>
                  </div>
                </div>
              </article>
            ))}

            {/* Pagination Controls */}
            {pagination.totalPages > 1 && (
              <div className="flex items-center justify-between pt-8 border-t border-[#E8E7E3]">
                <button
                  disabled={pagination.page <= 1}
                  onClick={() => {
                    const params = new URLSearchParams(searchParams);
                    params.set("page", String(pagination.page - 1));
                    setSearchParams(params);
                  }}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white border border-[#E8E7E3] text-sm font-medium text-[#111114] disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#F4F4F5] transition-colors"
                >
                  <ChevronLeft size={16} />
                  Previous
                </button>

                <span className="text-xs font-semibold text-[#6B6B72]">
                  Page {pagination.page} of {pagination.totalPages}
                </span>

                <button
                  disabled={pagination.page >= pagination.totalPages}
                  onClick={() => {
                    const params = new URLSearchParams(searchParams);
                    params.set("page", String(pagination.page + 1));
                    setSearchParams(params);
                  }}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-white border border-[#E8E7E3] text-sm font-medium text-[#111114] disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#F4F4F5] transition-colors"
                >
                  Next
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
};
