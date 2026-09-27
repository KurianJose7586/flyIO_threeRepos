import React, { useState } from "react";
import axios from "axios";
import { Lock, Loader2, AlertCircle } from "lucide-react";

interface LoginScreenProps {
  onLoginSuccess: (token: string, username: string) => void;
}

export const LoginScreen: React.FC<LoginScreenProps> = ({ onLoginSuccess }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password) {
      setError("Both username and password are required.");
      return;
    }

    setLoading(true);
    try {
      const res = await axios.post<{
        success: boolean;
        token: string;
        admin: { id: number; username: string };
      }>("/api/admin/login", { username: username.trim(), password });

      if (res.data.success && res.data.token) {
        localStorage.setItem("cms_admin_token", res.data.token);
        localStorage.setItem("cms_admin_username", res.data.admin.username);
        onLoginSuccess(res.data.token, res.data.admin.username);
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail || "Login failed. Please check your credentials.";
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="admin-layout">
      <div className="admin-login-wrapper">
        <div className="admin-login-card">
          {/* Brand */}
          <div style={{ textAlign: "center", marginBottom: "1.5rem" }}>
            <div style={{
              width: "52px",
              height: "52px",
              borderRadius: "16px",
              background: "linear-gradient(135deg, #7C3AED, #ec4899)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 1rem",
              boxShadow: "0 4px 20px rgba(124, 58, 237, 0.2)",
            }}>
              <Lock size={24} color="#fff" />
            </div>
            <div className="admin-login-title">
              Flyio<span style={{ color: "#7C3AED" }}>.ai</span> Admin
            </div>
            <div className="admin-login-subtitle">
              Sign in to manage your CMS content
            </div>
          </div>

          {error && (
            <div className="admin-toast admin-toast-error" style={{ marginBottom: "1rem" }}>
              <AlertCircle size={14} />
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="admin-field">
              <label className="admin-field-label">Username</label>
              <input
                className="admin-input"
                type="text"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loading}
                autoFocus
                autoComplete="username"
              />
            </div>

            <div className="admin-field">
              <label className="admin-field-label">Password</label>
              <input
                className="admin-input"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                autoComplete="current-password"
              />
            </div>

            <button
              type="submit"
              className="admin-btn admin-btn-primary"
              disabled={loading}
              style={{ width: "100%", justifyContent: "center", padding: "0.75rem", marginTop: "0.25rem", fontSize: "0.875rem" }}
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Lock size={14} />}
              {loading ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <div style={{
            textAlign: "center",
            marginTop: "1.5rem",
            fontSize: "0.6875rem",
            color: "#b5b5c3",
            letterSpacing: "0.02em",
          }}>
            Protected area · Unauthorized access prohibited
          </div>
        </div>
      </div>
    </div>
  );
};
