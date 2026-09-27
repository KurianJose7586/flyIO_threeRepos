import React, { useState, useEffect } from "react";
import { getAdminTripPackages, deleteTripPackage } from "./adminApi";
import type { TripPackage } from "./adminApi";
import { Compass, Plus, Edit3, Trash2, Clock, Globe, DollarSign } from "lucide-react";

interface AdminTripListProps {
  onEditTrip: (id: number) => void;
  onCreateTrip: () => void;
}

export const AdminTripList: React.FC<AdminTripListProps> = ({
  onEditTrip,
  onCreateTrip,
}) => {
  const [trips, setTrips] = useState<TripPackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const loadTrips = async () => {
    setLoading(true);
    try {
      const data = await getAdminTripPackages();
      setTrips(data);
    } catch (err: any) {
      setToast({ type: "error", message: "Failed to load trip packages: " + (err.message || String(err)) });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTrips();
  }, []);

  const handleDelete = async (id: number, title: string) => {
    if (!confirm(`Delete trip package "${title}"? This cannot be undone.`)) return;
    try {
      await deleteTripPackage(id);
      setToast({ type: "success", message: `Trip package "${title}" deleted.` });
      loadTrips();
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
        Loading trip packages...
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
          <Compass size={16} />
          Pre-Planned Trip Packages ({trips.length})
        </div>
        <button className="admin-btn admin-btn-create" onClick={onCreateTrip}>
          <Plus size={14} />
          New Trip Package
        </button>
      </div>

      {trips.length === 0 ? (
        <div className="admin-empty">
          <div className="admin-empty-icon">🗺️</div>
          No trip packages created yet. Click "New Trip Package" to author your first itinerary.
        </div>
      ) : (
        trips.map((trip) => {
          const isPublished = Boolean(trip.published_at);
          return (
            <div key={trip.id} className="admin-card">
              <div className="admin-card-info" onClick={() => onEditTrip(trip.id)}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <div className="admin-card-title">{trip.title}</div>
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
                  {trip.price_tier && (
                    <span
                      style={{
                        fontSize: "0.65rem",
                        fontWeight: 600,
                        padding: "0.15rem 0.45rem",
                        borderRadius: "12px",
                        background: "rgba(255, 87, 34, 0.08)",
                        color: "var(--admin-orange)",
                      }}
                    >
                      <DollarSign size={10} style={{ display: "inline", verticalAlign: "-1px" }} />
                      {trip.price_tier}
                    </span>
                  )}
                </div>
                <div className="admin-card-meta">
                  <span className="admin-card-slug">/trips/{trip.slug}</span>
                  <span className="admin-card-time">
                    <Clock size={11} />
                    {isPublished ? `Published ${formatDate(trip.published_at!)}` : `Updated ${formatDate(trip.updated_at)}`}
                  </span>
                </div>
              </div>

              <div className="admin-card-actions">
                {isPublished && (
                  <a
                    href={`/trips/${trip.slug}`}
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
                  onClick={() => onEditTrip(trip.id)}
                  title="Edit"
                >
                  <Edit3 size={14} />
                </button>
                <button
                  className="admin-btn admin-btn-danger admin-btn-icon"
                  onClick={() => handleDelete(trip.id, trip.title)}
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
