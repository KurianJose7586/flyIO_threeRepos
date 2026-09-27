import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getPublicBlogPostBySlug } from "../services/api";
import type { PublicBlogPost } from "../services/api";
import { ArrowLeft, Calendar, BookOpen, Share2, User, Folder, Tag as TagIcon } from "lucide-react";

export const BlogPostPage: React.FC = () => {
  const { slug } = useParams<{ slug: string }>();
  const [post, setPost] = useState<PublicBlogPost | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError("");

    getPublicBlogPostBySlug(slug)
      .then((data) => {
        if (data) {
          setPost(data);

          // SEO Plumbing: Dynamic document title & meta description update
          const pageTitle = data.meta_title || `${data.title} | Flyio.ai Travel Blog`;
          document.title = pageTitle;

          const metaDescTag = document.querySelector('meta[name="description"]');
          if (metaDescTag) {
            metaDescTag.setAttribute("content", data.meta_description || data.summary || data.title);
          } else {
            const newMeta = document.createElement("meta");
            newMeta.name = "description";
            newMeta.content = data.meta_description || data.summary || data.title;
            document.head.appendChild(newMeta);
          }
        } else {
          setError(`Article not found.`);
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load article.");
      })
      .finally(() => setLoading(false));

    return () => {
      document.title = "Flyio.ai - AI Travel Assistant";
    };
  }, [slug]);

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FAFAF9] flex items-center justify-center p-6 text-[#6B6B72]">
        <div className="text-center space-y-3">
          <div className="text-3xl animate-bounce">📖</div>
          <p className="text-sm font-medium">Loading article...</p>
        </div>
      </div>
    );
  }

  if (error || !post) {
    return (
      <div className="min-h-screen bg-[#FAFAF9] flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-white border border-[#E8E7E3] rounded-2xl p-8 text-center space-y-4 shadow-xs">
          <div className="w-12 h-12 rounded-full bg-red-50 text-red-500 mx-auto flex items-center justify-center">
            <BookOpen size={24} />
          </div>
          <h2 className="text-xl font-bold text-[#111114]">Article Not Found</h2>
          <p className="text-sm text-[#6B6B72]">{error || "The requested article does not exist or has been removed."}</p>
          <Link
            to="/blog"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#111114] text-white text-sm font-semibold hover:bg-black transition-colors"
          >
            <ArrowLeft size={16} />
            Back to Blog List
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FAFAF9] text-[#111114]">
      {/* Header Bar */}
      <header className="border-b border-[#E8E7E3] bg-white sticky top-0 z-40">
        <div className="max-w-4xl mx-auto px-4 py-4 flex items-center justify-between">
          <Link to="/blog" className="inline-flex items-center gap-2 text-sm font-semibold text-[#6B6B72] hover:text-[#111114] transition-colors">
            <ArrowLeft size={16} />
            <span>Back to All Articles</span>
          </Link>
          <button
            onClick={handleShare}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#F4F4F5] hover:bg-[#E4E4E7] text-xs font-semibold text-[#111114] transition-colors"
          >
            <Share2 size={13} />
            <span>{copied ? "Link Copied!" : "Share"}</span>
          </button>
        </div>
      </header>

      {/* Main Article Content */}
      <main className="max-w-3xl mx-auto px-4 py-12 md:py-16">
        <article className="bg-white border border-[#E8E7E3] rounded-2xl overflow-hidden shadow-xs space-y-8">
          {/* Featured Banner */}
          {post.banner && (
            <div className="w-full h-64 md:h-96 overflow-hidden bg-gray-100">
              <img
                src={post.banner}
                alt={post.title}
                className="w-full h-full object-cover"
              />
            </div>
          )}

          <div className="p-8 md:p-12 space-y-8">
            <header className="border-b border-[#E8E7E3] pb-8 space-y-4">
              <div className="flex flex-wrap items-center gap-3 text-xs text-[#6B6B72]">
                {post.category_name && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-[#7C3AED15] text-[#7C3AED] font-semibold">
                    <Folder size={12} />
                    {post.category_name}
                  </span>
                )}
                {post.author && (
                  <span className="inline-flex items-center gap-1 font-medium text-[#111114]">
                    <User size={12} className="text-[#7C3AED]" />
                    {post.author}
                  </span>
                )}
                <div className="flex items-center gap-1 font-medium">
                  <Calendar size={13} className="text-[#7C3AED]" />
                  <span>Published {formatDate(post.published_at)}</span>
                </div>
              </div>

              <h1 className="text-3xl md:text-4xl lg:text-5xl font-extrabold text-[#111114] tracking-tight leading-tight">
                {post.title}
              </h1>

              {post.summary && (
                <p className="text-lg text-[#4B5563] leading-relaxed font-normal">
                  {post.summary}
                </p>
              )}

              {post.meta_description && !post.summary && (
                <p className="text-base text-[#6B6B72] leading-relaxed italic border-l-2 border-[#7C3AED] pl-4">
                  {post.meta_description}
                </p>
              )}
            </header>

            <div
              className="prose prose-neutral max-w-none text-base text-[#333338] leading-relaxed font-sans"
              dangerouslySetInnerHTML={{ __html: post.body }}
            />

            {/* Tags Section */}
            {post.tags && post.tags.length > 0 && (
              <div className="border-t border-[#E8E7E3] pt-6 flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-[#6B6B72] mr-1 flex items-center gap-1">
                  <TagIcon size={12} /> Tags:
                </span>
                {post.tags.map((tag) => (
                  <span
                    key={tag.id}
                    className="inline-block text-xs font-medium px-2.5 py-1 rounded-lg bg-[#F4F4F5] text-[#333338]"
                  >
                    #{tag.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        </article>
      </main>
    </div>
  );
};
