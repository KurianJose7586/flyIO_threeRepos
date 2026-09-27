import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getCmsPage } from "../services/api";
import { ArrowLeft, Clock, FileText } from "lucide-react";

export const CMSPageView: React.FC = () => {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<{ slug: string; title: string; body: string; updated_at?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError("");

    getCmsPage(slug)
      .then((data) => {
        if (data) {
          setPage(data);
        } else {
          setError(`Page "${slug}" not found.`);
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load page.");
      })
      .finally(() => setLoading(false));
  }, [slug]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FAFAF9] flex items-center justify-center p-6 text-[#6B6B72]">
        <div className="text-center space-y-3">
          <div className="text-3xl animate-bounce">📄</div>
          <p className="text-sm font-medium">Loading page content...</p>
        </div>
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="min-h-screen bg-[#FAFAF9] flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-white border border-[#E8E7E3] rounded-2xl p-8 text-center space-y-4 shadow-xs">
          <div className="w-12 h-12 rounded-full bg-red-50 text-red-500 mx-auto flex items-center justify-center">
            <FileText size={24} />
          </div>
          <h2 className="text-xl font-bold text-[#111114]">Page Not Found</h2>
          <p className="text-sm text-[#6B6B72]">{error || "The page you are looking for does not exist."}</p>
          <Link
            to="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#111114] text-white text-sm font-semibold hover:bg-black transition-colors"
          >
            <ArrowLeft size={16} />
            Back to Home
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
          <Link to="/" className="inline-flex items-center gap-2 text-sm font-semibold text-[#6B6B72] hover:text-[#111114] transition-colors">
            <ArrowLeft size={16} />
            <span>Back to Flyio.ai</span>
          </Link>
          <div className="inline-flex items-center gap-2 text-xs text-[#6B6B72]">
            <Clock size={13} />
            <span>Updated from CMS</span>
          </div>
        </div>
      </header>

      {/* Main Content Article */}
      <main className="max-w-3xl mx-auto px-4 py-12 md:py-16">
        <div className="bg-white border border-[#E8E7E3] rounded-2xl p-8 md:p-12 shadow-xs space-y-6">
          <div className="border-b border-[#E8E7E3] pb-6">
            <h1 className="text-3xl md:text-4xl font-extrabold text-[#111114] tracking-tight">
              {page.title}
            </h1>
            <p className="text-xs text-[#6B6B72] mt-2 font-mono">
              /{page.slug}
            </p>
          </div>

          <div
            className="prose prose-neutral max-w-none text-base text-[#333338] leading-relaxed whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ __html: page.body }}
          />
        </div>
      </main>
    </div>
  );
};
