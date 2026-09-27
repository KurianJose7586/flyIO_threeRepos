import React, { useState, useEffect } from "react";
import { Dashboard } from "./Dashboard";
import { ContentEditor } from "./ContentEditor";
import { AdminBlogList } from "./AdminBlogList";
import { AdminBlogEditor } from "./AdminBlogEditor";
import { AdminTripList } from "./AdminTripList";
import { AdminTripEditor } from "./AdminTripEditor";
import { KnowledgeBaseCrawler } from "./KnowledgeBaseCrawler";
import { AdminKnowledgeBaseList } from "./AdminKnowledgeBaseList";
import { AdminCrawlHistory } from "./AdminCrawlHistory";
import { AdminBlogCategories } from "./AdminBlogCategories";
import { AdminBlogTags } from "./AdminBlogTags";
import { LoginScreen } from "./LoginScreen";
import { ExternalLink, LogOut, User, LayoutDashboard, BookOpen, Compass, Database, History } from "lucide-react";
import axios from "axios";
import "./admin.css";

type AdminView =
  | { screen: "dashboard" }
  | { screen: "edit-page"; slug: string }
  | { screen: "create-page" }
  | { screen: "edit-content"; key: string }
  | { screen: "create-content" }
  | { screen: "blog-list" }
  | { screen: "edit-blog"; id: number }
  | { screen: "create-blog" }
  | { screen: "blog-categories" }
  | { screen: "blog-tags" }
  | { screen: "trip-list" }
  | { screen: "edit-trip"; id: number }
  | { screen: "create-trip" }
  | { screen: "knowledge-base" }
  | { screen: "crawl-history" };

export const AdminApp: React.FC = () => {
  const [view, setView] = useState<AdminView>({ screen: "dashboard" });
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [adminUsername, setAdminUsername] = useState("");
  const [checking, setChecking] = useState(true);
  // Increment to trigger KB list refresh after a crawl
  const [kbRefreshKey, setKbRefreshKey] = useState(0);

  useEffect(() => {
    const token = localStorage.getItem("cms_admin_token");
    const username = localStorage.getItem("cms_admin_username");

    if (!token) {
      setChecking(false);
      return;
    }

    axios
      .get("/api/admin/me", { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (res.data.success) {
          setIsAuthenticated(true);
          setAdminUsername(res.data.admin?.username || username || "admin");
        } else {
          localStorage.removeItem("cms_admin_token");
          localStorage.removeItem("cms_admin_username");
        }
      })
      .catch(() => {
        localStorage.removeItem("cms_admin_token");
        localStorage.removeItem("cms_admin_username");
      })
      .finally(() => setChecking(false));
  }, []);

  const handleLoginSuccess = (_token: string, username: string) => {
    setIsAuthenticated(true);
    setAdminUsername(username);
    setView({ screen: "dashboard" });
  };

  const handleLogout = () => {
    localStorage.removeItem("cms_admin_token");
    localStorage.removeItem("cms_admin_username");
    setIsAuthenticated(false);
    setAdminUsername("");
    setView({ screen: "dashboard" });
  };

  const goToDashboard = () => setView({ screen: "dashboard" });
  const goToBlogList = () => setView({ screen: "blog-list" });
  const goToTripList = () => setView({ screen: "trip-list" });
  const goToKnowledgeBase = () => setView({ screen: "knowledge-base" });
  const goToCrawlHistory = () => setView({ screen: "crawl-history" });

  if (checking) {
    return (
      <div className="admin-layout">
        <div className="admin-empty" style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="admin-empty-icon">⏳</div>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen onLoginSuccess={handleLoginSuccess} />;
  }

  const isBlog = view.screen === "blog-list" || view.screen === "edit-blog" || view.screen === "create-blog" || view.screen === "blog-categories" || view.screen === "blog-tags";
  const isTrip = view.screen === "trip-list" || view.screen === "edit-trip" || view.screen === "create-trip";
  const isKb = view.screen === "knowledge-base";
  const isHistory = view.screen === "crawl-history";
  const activeTab = isBlog ? "blog" : isTrip ? "trips" : isKb ? "knowledge-base" : isHistory ? "crawl-history" : "pages";

  return (
    <div className="admin-layout">
      <header className="admin-header">
        <div className="admin-header-brand" onClick={goToDashboard}>
          <div className="brand-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
          </div>
          <span>
            Flyio<span style={{ color: "#7C3AED" }}>.ai</span>
          </span>
          <span className="badge">Admin</span>
        </div>

        <nav style={{ display: "flex", gap: "0.5rem" }}>
          <button
            className={`admin-btn ${activeTab === "pages" ? "admin-btn-primary" : "admin-btn-secondary"}`}
            onClick={goToDashboard}
            style={{ fontSize: "0.8rem", padding: "0.4rem 0.8rem" }}
          >
            <LayoutDashboard size={13} />
            Pages & Content
          </button>
          <button
            className={`admin-btn ${activeTab === "blog" ? "admin-btn-primary" : "admin-btn-secondary"}`}
            onClick={goToBlogList}
            style={{ fontSize: "0.8rem", padding: "0.4rem 0.8rem" }}
          >
            <BookOpen size={13} />
            Blog Posts
          </button>
          <button
            className={`admin-btn ${activeTab === "trips" ? "admin-btn-primary" : "admin-btn-secondary"}`}
            onClick={goToTripList}
            style={{ fontSize: "0.8rem", padding: "0.4rem 0.8rem" }}
          >
            <Compass size={13} />
            Trip Packages
          </button>
          <button
            id="nav-knowledge-base"
            className={`admin-btn ${activeTab === "knowledge-base" ? "admin-btn-primary" : "admin-btn-secondary"}`}
            onClick={goToKnowledgeBase}
            style={{ fontSize: "0.8rem", padding: "0.4rem 0.8rem" }}
          >
            <Database size={13} />
            Knowledge Base
          </button>
          <button
            id="nav-crawl-history"
            className={`admin-btn ${activeTab === "crawl-history" ? "admin-btn-primary" : "admin-btn-secondary"}`}
            onClick={goToCrawlHistory}
            style={{ fontSize: "0.8rem", padding: "0.4rem 0.8rem" }}
          >
            <History size={13} />
            Crawl History
          </button>
        </nav>

        <div className="admin-header-nav">
          <a href="/" className="admin-header-link">
            <ExternalLink size={13} />
            View Site
          </a>

          <div className="admin-header-user">
            <div className="avatar">
              <User size={11} />
            </div>
            <span>{adminUsername}</span>
          </div>

          <button
            className="admin-btn admin-btn-secondary"
            onClick={handleLogout}
            style={{ padding: "0.3rem 0.6rem", fontSize: "0.75rem" }}
          >
            <LogOut size={12} />
          </button>
        </div>
      </header>

      <div className="admin-container">
        {view.screen === "dashboard" && (
          <Dashboard
            onEditPage={(slug) => setView({ screen: "edit-page", slug })}
            onEditContent={(key) => setView({ screen: "edit-content", key })}
            onCreatePage={() => setView({ screen: "create-page" })}
            onCreateContent={() => setView({ screen: "create-content" })}
          />
        )}
        {view.screen === "edit-page" && (
          <ContentEditor mode="edit-page" identifier={view.slug} onBack={goToDashboard} />
        )}
        {view.screen === "create-page" && (
          <ContentEditor mode="create-page" onBack={goToDashboard} />
        )}
        {view.screen === "edit-content" && (
          <ContentEditor mode="edit-content" identifier={view.key} onBack={goToDashboard} />
        )}
        {view.screen === "create-content" && (
          <ContentEditor mode="create-content" onBack={goToDashboard} />
        )}
        {view.screen === "blog-list" && (
          <AdminBlogList
            onEditBlog={(id) => setView({ screen: "edit-blog", id })}
            onCreateBlog={() => setView({ screen: "create-blog" })}
            onManageCategories={() => setView({ screen: "blog-categories" })}
            onManageTags={() => setView({ screen: "blog-tags" })}
          />
        )}
        {view.screen === "blog-categories" && (
          <AdminBlogCategories onBack={goToBlogList} />
        )}
        {view.screen === "blog-tags" && (
          <AdminBlogTags onBack={goToBlogList} />
        )}
        {view.screen === "create-blog" && (
          <AdminBlogEditor onBack={goToBlogList} />
        )}
        {view.screen === "edit-blog" && (
          <AdminBlogEditor postId={view.id} onBack={goToBlogList} />
        )}
        {view.screen === "trip-list" && (
          <AdminTripList
            onEditTrip={(id) => setView({ screen: "edit-trip", id })}
            onCreateTrip={() => setView({ screen: "create-trip" })}
          />
        )}
        {view.screen === "create-trip" && (
          <AdminTripEditor onBack={goToTripList} />
        )}
        {view.screen === "edit-trip" && (
          <AdminTripEditor tripId={view.id} onBack={goToTripList} />
        )}
        {view.screen === "knowledge-base" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
            <KnowledgeBaseCrawler
              onCrawlComplete={() => setKbRefreshKey((k) => k + 1)}
            />
            <AdminKnowledgeBaseList refreshKey={kbRefreshKey} />
          </div>
        )}
        {view.screen === "crawl-history" && (
          <AdminCrawlHistory />
        )}
      </div>
    </div>
  );
};
