import axios from "axios";
import type { ChatResponse, HealthResponse, DebugConfigResponse } from "../types";

/**
 * Checks system health status.
 */
export const getHealth = async (): Promise<HealthResponse> => {
  const response = await axios.get<HealthResponse>("/health");
  return response.data;
};

/**
 * Retrieves internal debug configuration settings.
 * Returns null if the debug endpoint is disabled (e.g. in production).
 */
export const getDebugConfig = async (): Promise<DebugConfigResponse | null> => {
  try {
    const response = await axios.get<DebugConfigResponse>("/debug/config");
    return response.data;
  } catch (error) {
    console.warn("Debug configuration endpoint is unavailable (e.g. running in production mode).");
    return null;
  }
};

/**
 * Sends a natural language query to the RAG chat backend.
 */
export const sendChatQuery = async (query: string, hybridMode?: boolean): Promise<ChatResponse> => {
  const response = await axios.post<ChatResponse>("/chat", { query, hybridMode });
  return response.data;
};

/**
 * Direct lightweight fetch for destination attractions catalog without invoking LLM Orchestrator.
 */
export const getDestinationAttractions = async (destinationId: string) => {
  const response = await axios.get(`/destinations/${encodeURIComponent(destinationId)}/attractions`);
  return response.data;
};

/**
 * Fetch destination restaurants catalog.
 */
export const getDestinationRestaurants = async (destinationId: string) => {
  const response = await axios.get(`/destinations/${encodeURIComponent(destinationId)}/restaurants`);
  return response.data;
};

/**
 * Fetch destination how-to-reach transport guide.
 */
export const getDestinationHowToReach = async (destinationId: string) => {
  const response = await axios.get(`/destinations/${encodeURIComponent(destinationId)}/how-to-reach`);
  return response.data;
};

/**
 * Fetch destination 12-month weather & AQI records.
 */
export const getDestinationWeather = async (destinationId: string) => {
  const response = await axios.get(`/destinations/${encodeURIComponent(destinationId)}/weather`);
  return response.data;
};

/**
 * Fetch sample itinerary for destination.
 */
export const getDestinationItinerary = async (destinationId: string, days?: number) => {
  const response = await axios.get(`/destinations/${encodeURIComponent(destinationId)}/itinerary`, {
    params: { days }
  });
  return response.data;
};

/**
 * Fetch a CMS content block by key (public endpoint).
 */
export const getCmsContent = async (key: string): Promise<{ key: string; title?: string; body: string } | null> => {
  try {
    const response = await axios.get(`/api/cms/content/${encodeURIComponent(key)}`);
    if (response.data.success) {
      return response.data.content;
    }
    return null;
  } catch {
    return null;
  }
};

/**
 * Fetch a CMS page by slug (public endpoint).
 */
export const getCmsPage = async (slug: string): Promise<{ slug: string; title: string; body: string } | null> => {
  try {
    const response = await axios.get(`/api/cms/pages/${encodeURIComponent(slug)}`);
    if (response.data.success) {
      return response.data.page;
    }
    return null;
  } catch {
    return null;
  }
};

/**
 * Fetch all CMS pages for public navigation.
 */
export const getCmsPagesList = async (): Promise<Array<{ slug: string; title: string }>> => {
  try {
    const response = await axios.get("/api/cms/pages");
    if (response.data.success) {
      return response.data.pages;
    }
    return [];
  } catch {
    return [];
  }
};

// ── Public Blog API ──────────────────────────────────────────────────────────

export interface BlogTag {
  id: number;
  name: string;
  slug: string;
}

export interface PublicBlogPost {
  id: number;
  slug: string;
  title: string;
  body: string;
  summary?: string;
  author?: string;
  banner?: string;
  category_id?: number | null;
  category_name?: string;
  category_slug?: string;
  tags?: BlogTag[];
  meta_title?: string;
  meta_description?: string;
  published_at: string;
  created_at: string;
  updated_at: string;
}

export interface BlogListResponse {
  success: boolean;
  posts: PublicBlogPost[];
  pagination: {
    total: number;
    page: number;
    limit: number;
    totalPages: number;
  };
}

export const getPublicBlogPosts = async (
  page = 1,
  limit = 10,
  sort = "created_at",
  order = "desc"
): Promise<BlogListResponse> => {
  const response = await axios.get<BlogListResponse>("/api/blog/posts", {
    params: { page, limit, sort, order },
  });
  return response.data;
};

export const getPublicBlogPostBySlug = async (slug: string): Promise<PublicBlogPost | null> => {
  try {
    const response = await axios.get<{ success: boolean; post: PublicBlogPost }>(`/api/blog/posts/${encodeURIComponent(slug)}`);
    if (response.data.success) {
      return response.data.post;
    }
    return null;
  } catch {
    return null;
  }
};

// ── Public Trip Packages API ──────────────────────────────────────────────────

export interface PublicTripPackage {
  id: number;
  slug: string;
  title: string;
  description: string;
  itinerary_json: string;
  images?: string;
  price_tier?: string;
  published_at: string;
  created_at: string;
  updated_at: string;
}

export const getPublicTripPackages = async (): Promise<PublicTripPackage[]> => {
  const response = await axios.get<{ success: boolean; packages: PublicTripPackage[] }>("/api/trips/packages");
  return response.data.packages;
};

export const getPublicTripPackageBySlug = async (slug: string): Promise<PublicTripPackage | null> => {
  try {
    const response = await axios.get<{ success: boolean; package: PublicTripPackage }>(`/api/trips/packages/${encodeURIComponent(slug)}`);
    if (response.data.success) {
      return response.data.package;
    }
    return null;
  } catch {
    return null;
  }
};
