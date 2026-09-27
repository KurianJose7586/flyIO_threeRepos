import React, { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getPublicTripPackageBySlug } from "../services/api";
import type { PublicTripPackage } from "../services/api";
import { ArrowLeft, Compass, Calendar, DollarSign, CheckCircle2, Share2 } from "lucide-react";

interface ItineraryDay {
  day: number;
  title: string;
  activities?: string[];
  description?: string;
}

export const TripDetailPage: React.FC = () => {
  const { slug } = useParams<{ slug: string }>();
  const [pkg, setPkg] = useState<PublicTripPackage | null>(null);
  const [itineraryDays, setItineraryDays] = useState<ItineraryDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError("");

    getPublicTripPackageBySlug(slug)
      .then((data) => {
        if (data) {
          setPkg(data);

          // Dynamic Document Title for SEO
          document.title = `${data.title} | Flyio.ai Trip Packages`;

          // Parse itinerary JSON safely
          try {
            const parsed = typeof data.itinerary_json === "string"
              ? JSON.parse(data.itinerary_json)
              : data.itinerary_json;

            if (Array.isArray(parsed)) {
              setItineraryDays(parsed);
            } else if (parsed && Array.isArray(parsed.days)) {
              setItineraryDays(parsed.days);
            } else {
              setItineraryDays([]);
            }
          } catch {
            setItineraryDays([]);
          }
        } else {
          setError(`Trip package not found.`);
        }
      })
      .catch((err) => {
        setError(err.message || "Failed to load trip package.");
      })
      .finally(() => setLoading(false));

    return () => {
      document.title = "Flyio.ai - AI Travel Assistant";
    };
  }, [slug]);

  const handleShare = () => {
    navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FAFAF9] flex items-center justify-center p-6 text-[#6B6B72]">
        <div className="text-center space-y-3">
          <div className="text-3xl animate-bounce">🧭</div>
          <p className="text-sm font-medium">Loading itinerary...</p>
        </div>
      </div>
    );
  }

  if (error || !pkg) {
    return (
      <div className="min-h-screen bg-[#FAFAF9] flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-white border border-[#E8E7E3] rounded-2xl p-8 text-center space-y-4 shadow-xs">
          <div className="w-12 h-12 rounded-full bg-red-50 text-red-500 mx-auto flex items-center justify-center">
            <Compass size={24} />
          </div>
          <h2 className="text-xl font-bold text-[#111114]">Package Not Found</h2>
          <p className="text-sm text-[#6B6B72]">{error || "The requested trip package does not exist."}</p>
          <Link
            to="/trips"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#111114] text-white text-sm font-semibold hover:bg-black transition-colors"
          >
            <ArrowLeft size={16} />
            Back to Packages
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FAFAF9] text-[#111114]">
      {/* Header Bar */}
      <header className="border-b border-[#E8E7E3] bg-white sticky top-0 z-40">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <Link to="/trips" className="inline-flex items-center gap-2 text-sm font-semibold text-[#6B6B72] hover:text-[#111114] transition-colors">
            <ArrowLeft size={16} />
            <span>Back to All Packages</span>
          </Link>
          <button
            onClick={handleShare}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#F4F4F5] hover:bg-[#E4E4E7] text-xs font-semibold text-[#111114] transition-colors"
          >
            <Share2 size={13} />
            <span>{copied ? "Link Copied!" : "Share Package"}</span>
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-4 py-12 md:py-16 space-y-8">
        <div className="bg-white border border-[#E8E7E3] rounded-2xl p-8 md:p-12 shadow-xs space-y-6">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1 rounded-full bg-orange-50 text-[#FF5722]">
              <DollarSign size={12} />
              {pkg.price_tier || "Standard"}
            </span>
            {itineraryDays.length > 0 && (
              <span className="inline-flex items-center gap-1 text-xs font-semibold text-[#6B6B72]">
                <Calendar size={13} />
                {itineraryDays.length} Days Itinerary
              </span>
            )}
          </div>

          <h1 className="text-3xl md:text-4xl lg:text-5xl font-extrabold text-[#111114] tracking-tight leading-tight">
            {pkg.title}
          </h1>

          <p className="text-base text-[#6B6B72] leading-relaxed">
            {pkg.description}
          </p>
        </div>

        {/* Itinerary Schedule */}
        <div className="bg-white border border-[#E8E7E3] rounded-2xl p-8 md:p-12 shadow-xs space-y-8">
          <h2 className="text-2xl font-bold text-[#111114] flex items-center gap-2 border-b border-[#E8E7E3] pb-4">
            <Compass className="text-[#FF5722]" size={22} />
            <span>Daily Itinerary Plan</span>
          </h2>

          {itineraryDays.length === 0 ? (
            <div className="text-sm text-[#6B6B72] italic">
              No detailed daily schedule provided for this package.
            </div>
          ) : (
            <div className="space-y-8">
              {itineraryDays.map((dayItem, idx) => (
                <div key={idx} className="relative pl-8 border-l-2 border-[#FF5722] space-y-3">
                  <div className="absolute -left-[9px] top-0 w-4 h-4 rounded-full bg-[#FF5722] border-2 border-white" />

                  <div className="text-xs font-extrabold text-[#FF5722] uppercase tracking-wider">
                    Day {dayItem.day || idx + 1}
                  </div>

                  <h3 className="text-xl font-bold text-[#111114]">
                    {dayItem.title || `Day ${idx + 1}`}
                  </h3>

                  {dayItem.description && (
                    <p className="text-sm text-[#6B6B72] leading-relaxed">
                      {dayItem.description}
                    </p>
                  )}

                  {dayItem.activities && dayItem.activities.length > 0 && (
                    <ul className="space-y-2 pt-2">
                      {dayItem.activities.map((act, aIdx) => (
                        <li key={aIdx} className="flex items-start gap-2.5 text-sm text-[#333338]">
                          <CheckCircle2 size={16} className="text-[#10b981] mt-0.5 flex-shrink-0" />
                          <span>{act}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};
