import React, { useState, useEffect } from "react";
import { getAdminTripPackage, createTripPackage, updateTripPackage } from "./adminApi";
import { ArrowLeft, Save } from "lucide-react";

interface AdminTripEditorProps {
  tripId?: number; // if set, edit mode; if undefined, create mode
  onBack: () => void;
}

export const AdminTripEditor: React.FC<AdminTripEditorProps> = ({ tripId, onBack }) => {
  const isEdit = Boolean(tripId);

  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [itineraryJson, setItineraryJson] = useState(`[\n  {\n    "day": 1,\n    "title": "Arrival & Beach Exploration",\n    "activities": ["Check-in to resort", "Sunset at Baga Beach"]\n  }\n]`);
  const [images, setImages] = useState("");
  const [priceTier, setPriceTier] = useState("Standard");
  const [publish, setPublish] = useState(false);

  const [loading, setLoading] = useState(isEdit);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const generateSlug = (text: string) => {
    return text
      .toLowerCase()
      .trim()
      .replace(/[^\w\s-]/g, "")
      .replace(/[\s_-]+/g, "-")
      .replace(/^-+|-+$/g, "");
  };

  useEffect(() => {
    if (!isEdit || !tripId) return;
    setLoading(true);
    getAdminTripPackage(tripId)
      .then((trip) => {
        setTitle(trip.title);
        setSlug(trip.slug);
        setDescription(trip.description);
        try {
          // Pretty print JSON if valid
          const parsed = JSON.parse(trip.itinerary_json);
          setItineraryJson(JSON.stringify(parsed, null, 2));
        } catch {
          setItineraryJson(trip.itinerary_json);
        }
        setImages(trip.images || "");
        setPriceTier(trip.price_tier || "Standard");
        setPublish(Boolean(trip.published_at));
      })
      .catch((err) => {
        setToast({ type: "error", message: "Failed to load trip package: " + (err.message || String(err)) });
      })
      .finally(() => setLoading(false));
  }, [tripId, isEdit]);

  const handleTitleChange = (val: string) => {
    setTitle(val);
    if (!isEdit && !slug) {
      setSlug(generateSlug(val));
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !slug.trim() || !description.trim() || !itineraryJson.trim()) {
      setToast({ type: "error", message: "Title, Slug, Description, and Itinerary JSON are required." });
      return;
    }

    // Validate JSON structure before submitting
    try {
      JSON.parse(itineraryJson);
    } catch {
      setToast({ type: "error", message: "Itinerary JSON is invalid. Please ensure proper JSON formatting." });
      return;
    }

    setSaving(true);
    setToast(null);

    try {
      if (isEdit && tripId) {
        await updateTripPackage(tripId, {
          title,
          slug,
          description,
          itinerary_json: itineraryJson,
          images,
          price_tier: priceTier,
          publish,
        });
        setToast({ type: "success", message: "Trip package updated successfully." });
      } else {
        await createTripPackage({
          title,
          slug,
          description,
          itinerary_json: itineraryJson,
          images,
          price_tier: priceTier,
          publish,
        });
        setToast({ type: "success", message: "Trip package created successfully." });
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
        Loading trip editor...
      </div>
    );
  }

  return (
    <div className="admin-fade-in" style={{ maxWidth: "800px", margin: "0 auto" }}>
      {toast && (
        <div className={`admin-toast ${toast.type === "success" ? "admin-toast-success" : "admin-toast-error"}`}>
          {toast.type === "success" ? "✓" : "✕"} {toast.message}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem" }}>
        <button className="admin-btn admin-btn-secondary" onClick={onBack}>
          <ArrowLeft size={14} />
          Back to Trip Packages
        </button>
        <h2 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>
          {isEdit ? `Edit Trip Package #${tripId}` : "Create New Trip Package"}
        </h2>
      </div>

      <form onSubmit={handleSave} className="admin-form-card">
        <div className="admin-form-group">
          <label className="admin-form-label">Package Title *</label>
          <input
            type="text"
            className="admin-input"
            value={title}
            onChange={(e) => handleTitleChange(e.target.value)}
            placeholder="e.g. Goa 4-Day Coastal Escape"
            required
          />
        </div>

        <div className="admin-form-group">
          <label className="admin-form-label">URL Slug *</label>
          <input
            type="text"
            className="admin-input"
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/\s+/g, "-"))}
            placeholder="e.g. goa-4-day-coastal-escape"
            required
          />
          <span style={{ fontSize: "0.75rem", color: "var(--admin-text-secondary)", marginTop: "0.25rem", display: "block" }}>
            Live URL preview: <code>/trips/{slug || "your-slug"}</code>
          </span>
        </div>

        <div className="admin-form-group">
          <label className="admin-form-label">Package Description *</label>
          <textarea
            className="admin-textarea"
            rows={4}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Overview of the trip package, target travelers, highlights..."
            required
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          <div className="admin-form-group">
            <label className="admin-form-label">Price Tier</label>
            <select
              className="admin-input"
              value={priceTier}
              onChange={(e) => setPriceTier(e.target.value)}
            >
              <option value="Budget">Budget (₹)</option>
              <option value="Standard">Standard (₹₹)</option>
              <option value="Luxury">Luxury (₹₹₹)</option>
              <option value="Ultra-Luxury">Ultra-Luxury (₹₹₹₹)</option>
            </select>
          </div>

          <div className="admin-form-group">
            <label className="admin-form-label">Image URLs (comma-separated or JSON)</label>
            <input
              type="text"
              className="admin-input"
              value={images}
              onChange={(e) => setImages(e.target.value)}
              placeholder="https://images.unsplash.com/photo-1..., https://..."
            />
          </div>
        </div>

        <div className="admin-form-group">
          <label className="admin-form-label">Structured Itinerary JSON *</label>
          <textarea
            className="admin-textarea"
            rows={10}
            style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
            value={itineraryJson}
            onChange={(e) => setItineraryJson(e.target.value)}
            placeholder='[{"day": 1, "title": "Day 1 Title", "activities": ["Activity 1", "Activity 2"]}]'
            required
          />
        </div>

        <div style={{ borderTop: "1px solid var(--admin-border)", paddingTop: "1.25rem", marginTop: "1.5rem", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={publish}
              onChange={(e) => setPublish(e.target.checked)}
              style={{ width: "18px", height: "18px", accentColor: "var(--admin-accent)" }}
            />
            <span>Publish Package Immediately</span>
          </label>

          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button type="button" className="admin-btn admin-btn-secondary" onClick={onBack}>
              Cancel
            </button>
            <button type="submit" className="admin-btn admin-btn-create" disabled={saving}>
              <Save size={14} />
              {saving ? "Saving..." : isEdit ? "Update Package" : "Save Package"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};
