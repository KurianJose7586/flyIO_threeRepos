import React, { useEffect, useRef, useState } from "react";
import { getCKEditorConfig } from "./adminApi";

/**
 * CKEditorField — React wrapper for CKEditor 5 loaded from CDN.
 * Fetches toolbar config from the backend API (not hardcoded).
 *
 * Props:
 *  - value: current HTML content
 *  - onChange: callback when content changes
 */

declare global {
  interface Window {
    ClassicEditor?: {
      create(
        element: HTMLElement,
        config: Record<string, unknown>
      ): Promise<CKEditorInstance>;
    };
    CKEDITOR?: {
      ClassicEditor: {
        create(
          element: HTMLElement,
          config: Record<string, unknown>
        ): Promise<CKEditorInstance>;
      };
    };
  }
}

interface CKEditorInstance {
  getData(): string;
  setData(data: string): void;
  destroy(): Promise<void>;
  model: {
    document: {
      on(event: string, callback: () => void): void;
    };
  };
}

interface CKEditorFieldProps {
  value: string;
  onChange: (html: string) => void;
}

export const CKEditorField: React.FC<CKEditorFieldProps> = ({ value, onChange }) => {
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editorInstanceRef = useRef<CKEditorInstance | null>(null);
  const [toolbarConfig, setToolbarConfig] = useState<string[] | null>(null);
  const [editorReady, setEditorReady] = useState(false);
  const [error, setError] = useState("");
  const isSettingData = useRef(false);

  // Fetch toolbar config from backend
  useEffect(() => {
    getCKEditorConfig()
      .then((toolbar) => setToolbarConfig(toolbar))
      .catch((err) => {
        console.warn("Using default toolbar config:", err.message);
        setToolbarConfig([
          "heading", "|",
          "bold", "italic", "link",
          "bulletedList", "numberedList", "|",
          "blockQuote", "insertTable",
          "undo", "redo",
        ]);
      });
  }, []);

  // Poll for ClassicEditor on window if script tag is still resolving
  useEffect(() => {
    let attempts = 0;
    const maxAttempts = 30; // 3 seconds total
    const timer = setInterval(() => {
      const editorClass = window.ClassicEditor || window.CKEDITOR?.ClassicEditor;
      if (editorClass) {
        setEditorReady(true);
        clearInterval(timer);
      } else {
        attempts++;
        if (attempts >= maxAttempts) {
          clearInterval(timer);
          setError("CKEditor script not loaded from CDN. Using standard rich textarea.");
        }
      }
    }, 100);

    return () => clearInterval(timer);
  }, []);

  // Initialize CKEditor once config and editor class are ready
  useEffect(() => {
    if (!toolbarConfig || !editorReady || !editorContainerRef.current) return;

    const editorClass = window.ClassicEditor || window.CKEDITOR?.ClassicEditor;
    if (!editorClass) return;

    let destroyed = false;

    // Filter toolbar config to remove items unsupported by ClassicEditor build
    const validToolbarItems = toolbarConfig.filter((item) => typeof item === "string");

    editorClass.create(editorContainerRef.current, {
      toolbar: {
        items: validToolbarItems,
        shouldNotGroupWhenFull: true,
      },
      initialData: value || "",
    })
      .then((editor) => {
        if (destroyed) {
          editor.destroy().catch(() => {});
          return;
        }
        editorInstanceRef.current = editor;

        editor.model.document.on("change:data", () => {
          if (!isSettingData.current) {
            onChange(editor.getData());
          }
        });
      })
      .catch((err: Error) => {
        console.error("CKEditor initialization error:", err);
        setError("CKEditor could not initialize: " + err.message);
      });

    return () => {
      destroyed = true;
      if (editorInstanceRef.current) {
        editorInstanceRef.current.destroy().catch(() => {});
        editorInstanceRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolbarConfig, editorReady]);

  // Sync external value changes into CKEditor (e.g., loading existing post)
  useEffect(() => {
    if (editorInstanceRef.current) {
      const currentData = editorInstanceRef.current.getData();
      if (currentData !== value) {
        isSettingData.current = true;
        editorInstanceRef.current.setData(value || "");
        isSettingData.current = false;
      }
    }
  }, [value]);

  if (error) {
    return (
      <div style={{ color: "var(--admin-text)", fontSize: "0.85rem" }}>
        <div style={{
          background: "rgba(239, 68, 68, 0.1)",
          border: "1px solid rgba(239, 68, 68, 0.25)",
          color: "var(--admin-red)",
          padding: "0.5rem 0.75rem",
          borderRadius: 8,
          marginBottom: "0.5rem",
          fontSize: "0.75rem",
        }}>
          ⚠️ {error}
        </div>
        <textarea
          className="admin-textarea"
          rows={14}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter post body (HTML or Markdown supported)..."
          style={{ width: "100%", fontFamily: "inherit" }}
        />
      </div>
    );
  }

  if (!toolbarConfig || !editorReady) {
    return (
      <div style={{
        padding: "3rem",
        textAlign: "center",
        color: "var(--admin-text-muted)",
        background: "var(--admin-card-bg)",
        border: "1px solid var(--admin-border)",
        borderRadius: 8,
        fontSize: "0.85rem",
      }}>
        Initializing Rich Text Editor...
      </div>
    );
  }

  return (
    <div className="ckeditor-wrapper" style={{ color: "#1a1a1a" }}>
      <div ref={editorContainerRef} />
      <style>{`
        .ckeditor-wrapper .ck.ck-editor__main > .ck-editor__editable {
          min-height: 280px;
          background: #ffffff;
          color: #1a1a1a;
          border-bottom-left-radius: 8px;
          border-bottom-right-radius: 8px;
          font-family: inherit;
          font-size: 0.95rem;
          line-height: 1.6;
        }
        .ckeditor-wrapper .ck.ck-toolbar {
          border-top-left-radius: 8px;
          border-top-right-radius: 8px;
          background: #f8f9fa;
          border-color: #e2e8f0;
        }
        .ckeditor-wrapper .ck.ck-editor__editable.ck-focused {
          border-color: var(--admin-accent, #6366f1) !important;
          box-shadow: 0 0 0 1px var(--admin-accent, #6366f1) !important;
        }
      `}</style>
    </div>
  );
};
