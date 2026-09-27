import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "./index.css";
import { AdminApp } from "./admin/AdminApp";
import { CMSPageView } from "./components/CMSPageView";
import { BlogListPage } from "./pages/BlogListPage";
import { BlogPostPage } from "./pages/BlogPostPage";
import { TripListPage } from "./pages/TripListPage";
import { TripDetailPage } from "./pages/TripDetailPage";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        {/* Admin panel at /admin and default root */}
        <Route path="/admin/*" element={<AdminApp />} />
        
        {/* Dynamic CMS Page Viewer at /page/:slug */}
        <Route path="/page/:slug" element={<CMSPageView />} />
        
        {/* Public Blog routes */}
        <Route path="/blog" element={<BlogListPage />} />
        <Route path="/blog/:slug" element={<BlogPostPage />} />
        
        {/* Public Trip Package routes */}
        <Route path="/trips" element={<TripListPage />} />
        <Route path="/trips/:slug" element={<TripDetailPage />} />
        
        {/* Default route redirects to /admin */}
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
