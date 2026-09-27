import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getPublicTripPackages } from "../services/api";
import type { PublicTripPackage } from "../services/api";
import { Compass, ArrowRight, ArrowLeft, DollarSign } from "lucide-react";

export const TripListPage: React.FC = () => {
  const [packages, setPackages] = useState<PublicTripPackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");

    getPublicTripPackages()
      .then((data) => {
        setPackages(data);
      })
      .catch((err) => {
        setError(err.message || "Failed to load trip packages.");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-[#FAFAF9] text-[#111114]">
      {/* Header Bar */}
      <header className="border-b border-[#E8E7E3] bg-white sticky top-0 z-40">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <Link to="/" className="inline-flex items-center gap-2 text-sm font-semibold text-[#6B6B72] hover:text-[#111114] transition-colors">
            <ArrowLeft size={16} />
            <span>Back to Flyio.ai</span>
          </Link>
          <div className="inline-flex items-center gap-2 text-sm font-bold text-[#FF5722]">
            <Compass size={16} />
            <span>Pre-Planned Trip Packages</span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-5xl mx-auto px-4 py-12 md:py-16">
        <div className="text-center mb-12 space-y-3">
          <h1 className="text-3xl md:text-5xl font-extrabold text-[#111114] tracking-tight">
            Curated Trip Packages & Itineraries
          </h1>
          <p className="text-base text-[#6B6B72] max-w-xl mx-auto">
            Handcrafted travel plans authored by destination experts. Ready to book and explore.
          </p>
        </div>

        {loading ? (
          <div className="min-h-[300px] flex items-center justify-center p-6 text-[#6B6B72]">
            <div className="text-center space-y-3">
              <div className="text-3xl animate-bounce">🧭</div>
              <p className="text-sm font-medium">Loading trip packages...</p>
            </div>
          </div>
        ) : error ? (
          <div className="bg-white border border-[#E8E7E3] rounded-2xl p-8 text-center text-red-500 max-w-md mx-auto">
            {error}
          </div>
        ) : packages.length === 0 ? (
          <div className="bg-white border border-[#E8E7E3] rounded-2xl p-12 text-center space-y-3 max-w-md mx-auto">
            <div className="text-4xl">🎒</div>
            <h3 className="text-lg font-bold text-[#111114]">No Trip Packages Available</h3>
            <p className="text-sm text-[#6B6B72]">Check back soon for new curated itineraries!</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {packages.map((pkg) => (
              <article
                key={pkg.id}
                className="bg-white border border-[#E8E7E3] hover:border-[#FF5722] rounded-2xl p-6 md:p-8 transition-all duration-200 shadow-xs hover:shadow-md flex flex-col justify-between group"
              >
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1 text-xs font-bold px-3 py-1 rounded-full bg-orange-50 text-[#FF5722]">
                      <DollarSign size={12} />
                      {pkg.price_tier || "Standard"}
                    </span>
                  </div>

                  <h2 className="text-xl md:text-2xl font-bold text-[#111114] group-hover:text-[#FF5722] transition-colors">
                    <Link to={`/trips/${pkg.slug}`}>{pkg.title}</Link>
                  </h2>

                  <p className="text-sm text-[#6B6B72] line-clamp-3 leading-relaxed">
                    {pkg.description}
                  </p>
                </div>

                <div className="pt-6 border-t border-[#E8E7E3] mt-6 flex items-center justify-between">
                  <span className="text-xs text-[#6B6B72]">Full Daily Itinerary</span>
                  <Link
                    to={`/trips/${pkg.slug}`}
                    className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#FF5722] hover:text-[#E64A19] transition-colors"
                  >
                    <span>View Package</span>
                    <ArrowRight size={14} className="group-hover:translate-x-1 transition-transform" />
                  </Link>
                </div>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};
