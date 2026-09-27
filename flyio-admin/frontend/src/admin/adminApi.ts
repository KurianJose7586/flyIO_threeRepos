import axios from "axios";

/**
 * CMS Admin API service.
 * Mirrors the pattern in services/api.ts.
 */

// ── Types ────────────────────────────────────────────────────────────────────

export interface CmsPage {
  id: number;
  slug: string;
  title: string;
  body?: string;
  updated_at: string;
}

export interface CmsContent {
  id: number;
  key: string;
  title: string | null;
  body?: string;
  updated_at: string;
}

export interface BlogPost {
  id: number;
  slug: string;
  title: string;
  body: string;
  summary?: string;
  author?: string;
  banner?: string;
  category_id?: number | null;
  category_name?: string;
  tag_ids?: number[];
  meta_title?: string;
  meta_description?: string;
  published_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  created_at: string;
}

export interface Tag {
  id: number;
  name: string;
  slug: string;
  created_at: string;
}

// ── Auth header helper ───────────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("cms_admin_token");
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

// ── Pages API ────────────────────────────────────────────────────────────────

export const getPages = async (): Promise<CmsPage[]> => {
  const res = await axios.get<{ success: boolean; pages: CmsPage[] }>("/api/cms/pages");
  return res.data.pages;
};

export const getPage = async (slug: string): Promise<CmsPage> => {
  const res = await axios.get<{ success: boolean; page: CmsPage }>(`/api/cms/pages/${encodeURIComponent(slug)}`);
  return res.data.page;
};

export const createPage = async (slug: string, title: string, body: string): Promise<void> => {
  await axios.post("/api/cms/pages", { slug, title, body }, { headers: authHeaders() });
};

export const updatePage = async (slug: string, data: { title?: string; body?: string }): Promise<void> => {
  await axios.put(`/api/cms/pages/${encodeURIComponent(slug)}`, data, { headers: authHeaders() });
};

export const deletePage = async (slug: string): Promise<void> => {
  await axios.delete(`/api/cms/pages/${encodeURIComponent(slug)}`, { headers: authHeaders() });
};

// ── Site Content API ─────────────────────────────────────────────────────────

export const getContentList = async (): Promise<CmsContent[]> => {
  const res = await axios.get<{ success: boolean; content: CmsContent[] }>("/api/cms/content");
  return res.data.content;
};

export const getContent = async (key: string): Promise<CmsContent> => {
  const res = await axios.get<{ success: boolean; content: CmsContent }>(`/api/cms/content/${encodeURIComponent(key)}`);
  return res.data.content;
};

export const upsertContent = async (key: string, data: { title?: string; body: string }): Promise<void> => {
  await axios.put(`/api/cms/content/${encodeURIComponent(key)}`, data, { headers: authHeaders() });
};

// ── Blog API ──────────────────────────────────────────────────────────────────

export const getAdminBlogPosts = async (): Promise<BlogPost[]> => {
  const res = await axios.get<{ success: boolean; posts: BlogPost[] }>("/api/admin/blog/posts", {
    headers: authHeaders(),
  });
  return res.data.posts;
};

export const getAdminBlogPost = async (id: number): Promise<BlogPost> => {
  const res = await axios.get<{ success: boolean; post: BlogPost }>(`/api/admin/blog/posts/${id}`, {
    headers: authHeaders(),
  });
  return res.data.post;
};

export const createBlogPost = async (data: {
  title: string;
  slug: string;
  body: string;
  summary?: string;
  author?: string;
  banner?: string;
  category_id?: number | null;
  tag_ids?: number[];
  meta_title?: string;
  meta_description?: string;
  publish?: boolean;
}): Promise<void> => {
  await axios.post("/api/admin/blog/posts", data, { headers: authHeaders() });
};

export const updateBlogPost = async (
  id: number,
  data: {
    title?: string;
    slug?: string;
    body?: string;
    summary?: string;
    author?: string;
    banner?: string;
    category_id?: number | null;
    tag_ids?: number[];
    meta_title?: string;
    meta_description?: string;
    publish?: boolean;
  }
): Promise<void> => {
  await axios.put(`/api/admin/blog/posts/${id}`, data, { headers: authHeaders() });
};

export const deleteBlogPost = async (id: number): Promise<void> => {
  await axios.delete(`/api/admin/blog/posts/${id}`, { headers: authHeaders() });
};

// ── Banner Upload API ─────────────────────────────────────────────────────────

export const uploadBlogBanner = async (file: File): Promise<string> => {
  const formData = new FormData();
  formData.append("banner", file);
  const res = await axios.post<{ success: boolean; url: string }>(
    "/api/admin/blog/upload-banner",
    formData,
    { headers: { ...authHeaders(), "Content-Type": "multipart/form-data" } }
  );
  return res.data.url;
};

// ── Categories API ────────────────────────────────────────────────────────────

export const getCategories = async (): Promise<Category[]> => {
  const res = await axios.get<{ success: boolean; categories: Category[] }>("/api/admin/blog/categories", {
    headers: authHeaders(),
  });
  return res.data.categories;
};

export const createCategory = async (data: { name: string; slug: string }): Promise<void> => {
  await axios.post("/api/admin/blog/categories", data, { headers: authHeaders() });
};

export const updateCategory = async (id: number, data: { name?: string; slug?: string }): Promise<void> => {
  await axios.put(`/api/admin/blog/categories/${id}`, data, { headers: authHeaders() });
};

export const deleteCategory = async (id: number): Promise<void> => {
  await axios.delete(`/api/admin/blog/categories/${id}`, { headers: authHeaders() });
};

// ── Tags API ──────────────────────────────────────────────────────────────────

export const getTags = async (): Promise<Tag[]> => {
  const res = await axios.get<{ success: boolean; tags: Tag[] }>("/api/admin/blog/tags", {
    headers: authHeaders(),
  });
  return res.data.tags;
};

export const createTag = async (data: { name: string; slug: string }): Promise<void> => {
  await axios.post("/api/admin/blog/tags", data, { headers: authHeaders() });
};

export const updateTag = async (id: number, data: { name?: string; slug?: string }): Promise<void> => {
  await axios.put(`/api/admin/blog/tags/${id}`, data, { headers: authHeaders() });
};

export const deleteTag = async (id: number): Promise<void> => {
  await axios.delete(`/api/admin/blog/tags/${id}`, { headers: authHeaders() });
};

// ── CKEditor Config API ───────────────────────────────────────────────────────

export const getCKEditorConfig = async (): Promise<string[]> => {
  const res = await axios.get<{ success: boolean; toolbar: string[] }>("/api/admin/config/ckeditor", {
    headers: authHeaders(),
  });
  return res.data.toolbar;
};

// ── Trip Packages API ────────────────────────────────────────────────────────

export interface TripPackage {
  id: number;
  slug: string;
  title: string;
  description: string;
  itinerary_json: string;
  images?: string;
  price_tier?: string;
  published_at?: string | null;
  created_at: string;
  updated_at: string;
}

export const getAdminTripPackages = async (): Promise<TripPackage[]> => {
  const res = await axios.get<{ success: boolean; packages: TripPackage[] }>("/api/admin/trips/packages", {
    headers: authHeaders(),
  });
  return res.data.packages;
};

export const getAdminTripPackage = async (id: number): Promise<TripPackage> => {
  const res = await axios.get<{ success: boolean; package: TripPackage }>(`/api/admin/trips/packages/${id}`, {
    headers: authHeaders(),
  });
  return res.data.package;
};

export const createTripPackage = async (data: {
  title: string;
  slug: string;
  description: string;
  itinerary_json: string;
  images?: string;
  price_tier?: string;
  publish?: boolean;
}): Promise<void> => {
  await axios.post("/api/admin/trips/packages", data, { headers: authHeaders() });
};

export const updateTripPackage = async (
  id: number,
  data: {
    title?: string;
    slug?: string;
    description?: string;
    itinerary_json?: string;
    images?: string;
    price_tier?: string;
    publish?: boolean;
  }
): Promise<void> => {
  await axios.put(`/api/admin/trips/packages/${id}`, data, { headers: authHeaders() });
};

export const deleteTripPackage = async (id: number): Promise<void> => {
  await axios.delete(`/api/admin/trips/packages/${id}`, { headers: authHeaders() });
};

// ── Knowledge Base API ────────────────────────────────────────────────────────

/** Summary row returned by GET /api/admin/knowledge-base (grouped by source_url) */
export interface KnowledgeBaseEntry {
  source_url:  string;
  page_title:  string;
  chunk_count: number;
  /** Chunks that carry a Qdrant point ID, i.e. are in the vector DB. */
  ingested_count?: number;
  fetched_at:  string;
}

/** A single chunk returned by GET /api/admin/knowledge-base/chunks */
export interface KnowledgeBaseChunk {
  id:               number;
  /** Point ID returned by the LLM Store API; null when the chunk was never ingested. */
  qdrant_point_id?: string | null;
  vector_status?: "stored" | "pending" | "not_ingested";
  source_url:       string;
  page_title:       string;
  section_path:     string;
  chunk_index:      number;
  content_text:     string;
  content_html:     string;
  fetched_at:       string;
}

export interface CrawlResult {
  url:    string;
  status: "success" | "failed";
  chunks?: number;
  error?: string;
  /** Outcome of pushing this URL's chunks into the vector DB after scraping. */
  vector_status?: "stored" | "skipped" | "failed";
  vector_stored?: number;
  vector_error?: string;
}

export interface JobStatusResponse {
  success: boolean;
  job_id: string;
  status: "created" | "sent" | "pending" | "running" | "success" | "failed" | string;
  results?: CrawlResult[];
  error?: string;
  total?: number;
  succeeded?: number;
  failed?: number;
}

export interface CrawlSubmitResponse {
  success:   boolean;
  job_id?:   string;
  status?:   string;
  /** Explanation when nothing was crawled (e.g. status "skipped"). */
  detail?:   string;
  total?:    number;
  succeeded?: number;
  failed?:   number;
  results?:  CrawlResult[];
  error?:    string;
}

export interface JobUrlResult {
  url: string;
  status: "queued" | "running" | "success" | "failed" | "pending" | string;
  chunks: number;
  /** How many of `chunks` carry a Qdrant point ID, i.e. reached the vector DB. */
  vector_chunks?: number;
  vector_status?: "stored" | "partial" | "failed" | "pending" | null;
  /** Why chunks did not reach the vector DB, when they did not. */
  vector_error?: string | null;
  error: string | null;
  duration_ms: number | null;
}

export interface JobUrlResultsResponse {
  success: boolean;
  job_id: string;
  job_status: string;
  /** Why the job as a whole failed, when it did. */
  job_error?: string | null;
  urls: JobUrlResult[];
}

export interface Pagination {
  total:      number;
  page:       number;
  limit:      number;
  totalPages: number;
}

/**
 * GET /api/admin/jobs/:job_id/status
 * Fetches current job status and results if finished.
 */
export const getScrapeJobStatus = async (jobId: string): Promise<JobStatusResponse> => {
  const res = await axios.get<JobStatusResponse>(
    `/api/admin/jobs/${encodeURIComponent(jobId)}/status`,
    { headers: authHeaders() }
  );
  return res.data;
};

/**
 * Polls job status until it reaches a terminal status ('success' | 'failed') or times out.
 */
export const pollScrapeJob = async (
  jobId: string,
  options?: {
    intervalMs?: number;
    timeoutMs?: number;
    onProgress?: (status: JobStatusResponse) => void;
  }
): Promise<JobStatusResponse> => {
  const interval = options?.intervalMs ?? 2000;
  const timeout = options?.timeoutMs ?? 300000;
  const startTime = Date.now();

  while (Date.now() - startTime < timeout) {
    const jobStatus = await getScrapeJobStatus(jobId);
    if (options?.onProgress) {
      options.onProgress(jobStatus);
    }
    if (jobStatus.status === "success" || jobStatus.status === "failed") {
      return jobStatus;
    }
    await new Promise((resolve) => setTimeout(resolve, interval));
  }

  throw new Error(`Job status polling timed out after ${timeout}ms for job ${jobId}`);
};

/**
 * POST /api/admin/crawl
 * Accepts a raw text block (one URL per line).
 * Pass asyncMode=true to return job_id immediately without waiting.
 */
export const submitCrawlUrls = async (
  urls: string,
  options?: { asyncMode?: boolean }
): Promise<CrawlSubmitResponse> => {
  const asyncMode = options?.asyncMode ?? false;
  const res = await axios.post<CrawlSubmitResponse>(
    `/api/admin/crawl${asyncMode ? "?async=true" : ""}`,
    { urls },
    { headers: authHeaders() }
  );
  return res.data;
};

/**
 * GET /api/admin/jobs/:job_id/url-results
 * Returns per-URL progress for a job (status, chunks, error, duration_ms).
 * Poll this every 2s to update the UI cards in real time.
 */
export const getJobUrlResults = async (jobId: string): Promise<JobUrlResultsResponse> => {
  const res = await axios.get<JobUrlResultsResponse>(
    `/api/admin/jobs/${encodeURIComponent(jobId)}/url-results`,
    { headers: authHeaders() }
  );
  return res.data;
};

export interface JobSummary {
  id: string;
  operation: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface JobEventLog {
  id: number;
  event_type: string;
  detail: any;
  created_at: string;
}

export const getRecentJobs = async (): Promise<JobSummary[]> => {
  const res = await axios.get<{ success: boolean; jobs: JobSummary[] }>(
    `/api/admin/jobs?limit=5`,
    { headers: authHeaders() }
  );
  return res.data.jobs || [];
};

export const getJobDetail = async (jobId: string): Promise<{ job: JobSummary; events: JobEventLog[] }> => {
  const res = await axios.get<{ success: boolean; job: JobSummary; events: JobEventLog[] }>(
    `/api/admin/jobs/${encodeURIComponent(jobId)}`,
    { headers: authHeaders() }
  );
  return { job: res.data.job, events: res.data.events || [] };
};

/**
 * GET /api/admin/knowledge-base
 * Paginated list of crawled URLs with page_title and chunk count.
 */
export const getKnowledgeBaseEntries = async (
  page = 1,
  limit = 20
): Promise<{ entries: KnowledgeBaseEntry[]; pagination: Pagination }> => {
  const res = await axios.get<{ success: boolean; entries: KnowledgeBaseEntry[]; pagination: Pagination }>(
    `/api/admin/knowledge-base?page=${page}&limit=${limit}`,
    { headers: authHeaders() }
  );
  return { entries: res.data.entries, pagination: res.data.pagination };
};

/**
 * GET /api/admin/knowledge-base/chunks?source_url=...
 * All chunks for a specific source URL.
 */
export interface VectorSummary {
  total: number;
  ingested: number;
  pending: number;
  in_progress: boolean;
}

export const getKnowledgeBaseChunks = async (sourceUrl: string): Promise<KnowledgeBaseChunk[]> => {
  const res = await axios.get<{ success: boolean; chunks: KnowledgeBaseChunk[] }>(
    `/api/admin/knowledge-base/chunks?source_url=${encodeURIComponent(sourceUrl)}`,
    { headers: authHeaders() }
  );
  return res.data.chunks;
};

/**
 * Same endpoint as getKnowledgeBaseChunks, but also returns the per-URL
 * vector rollup so a caller can say "40 of 58 ingested, still running"
 * instead of counting nulls across the chunk list.
 */
export const getKnowledgeBaseChunksWithSummary = async (
  sourceUrl: string
): Promise<{ chunks: KnowledgeBaseChunk[]; vector_summary?: VectorSummary }> => {
  const res = await axios.get<{
    success: boolean;
    chunks: KnowledgeBaseChunk[];
    vector_summary?: VectorSummary;
  }>(
    `/api/admin/knowledge-base/chunks?source_url=${encodeURIComponent(sourceUrl)}`,
    { headers: authHeaders() }
  );
  return { chunks: res.data.chunks, vector_summary: res.data.vector_summary };
};

/**
 * DELETE /api/admin/knowledge-base?source_url=...
 * Deletes all chunks for a source URL from knowledge_base (history remains intact).
 */
export const deleteKnowledgeBaseEntry = async (sourceUrl: string): Promise<void> => {
  await axios.delete(
    `/api/admin/knowledge-base?source_url=${encodeURIComponent(sourceUrl)}`,
    { headers: authHeaders() }
  );
};

/**
 * DELETE /api/admin/knowledge-base?id=...
 * Deletes a specific chunk by ID from knowledge_base (history remains intact).
 */
export const deleteKnowledgeBaseChunk = async (chunkId: number): Promise<void> => {
  await axios.delete(
    `/api/admin/knowledge-base?id=${encodeURIComponent(chunkId)}`,
    { headers: authHeaders() }
  );
};

// ── Crawl History API ─────────────────────────────────────────────────────────

export interface CrawlHistoryEntry {
  id: number;
  url: string;
  status: "success" | "failed";
  error_message: string | null;
  created_at: string;
}

/**
 * GET /api/admin/crawl-history
 * Paginated list of all crawl history entries, newest first.
 */
export const getCrawlHistory = async (
  page = 1,
  limit = 50
): Promise<{ entries: CrawlHistoryEntry[]; pagination: Pagination }> => {
  const res = await axios.get<{ success: boolean; entries: CrawlHistoryEntry[]; pagination: Pagination }>(
    `/api/admin/crawl-history?page=${page}&limit=${limit}`,
    { headers: authHeaders() }
  );
  return { entries: res.data.entries, pagination: res.data.pagination };
};

/**
 * DELETE /api/admin/crawl-history?id=...
 */
export const deleteCrawlHistoryEntry = async (id: number): Promise<void> => {
  await axios.delete(
    `/api/admin/crawl-history?id=${encodeURIComponent(id)}`,
    { headers: authHeaders() }
  );
};

/**
 * DELETE /api/admin/crawl-history?ids=1,2,3
 */
export const deleteCrawlHistoryEntries = async (ids: number[]): Promise<void> => {
  if (ids.length === 0) return;
  await axios.delete(
    `/api/admin/crawl-history?ids=${encodeURIComponent(ids.join(","))}`,
    { headers: authHeaders() }
  );
};

/**
 * DELETE /api/admin/crawl-history?all=true
 */
export const clearAllCrawlHistory = async (): Promise<void> => {
  await axios.delete(
    `/api/admin/crawl-history?all=true`,
    { headers: authHeaders() }
  );
};

// ── LLM Orchestration & Prompt History API ────────────────────────────────────

export interface PromptHistoryItem {
  id: number;
  request_id: string;
  prompt_text: string;
  status: "pending" | "data_required" | "completed" | "failed" | string;
  metadata?: Record<string, unknown>;
  summary_message?: string;
  has_plan?: boolean;
  created_at: string;
  updated_at: string;
}

export interface RequestEventItem {
  id: number;
  request_id: string;
  service: string;
  event_type: string;
  status: string;
  message: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface PromptDetailResponse {
  success: boolean;
  prompt: {
    id: number;
    request_id: string;
    prompt_text: string;
    response_data: Record<string, unknown> | null;
    status: string;
    metadata: Record<string, unknown>;
    created_at: string;
    updated_at: string;
  };
  events: RequestEventItem[];
}

export interface LLMGenerateResult {
  success: boolean;
  request_id: string;
  status: string;
  plan?: Record<string, unknown> | null;
  results?: unknown[];
  message?: string;
  scraped_sources?: string[];
  execution_time_ms?: number;
  error?: unknown;
}

/**
 * POST /api/admin/llm/generate
 * Main orchestration request.
 */
export const generateLLMPlan = async (
  prompt: string,
  urls?: string[] | string,
  metadata?: Record<string, unknown>
): Promise<LLMGenerateResult> => {
  const res = await axios.post<LLMGenerateResult>(
    "/api/admin/llm/generate",
    { prompt, urls, metadata },
    { headers: authHeaders() }
  );
  return res.data;
};

/**
 * GET /api/admin/prompts
 * Paginated list of user prompts.
 */
export const getPromptHistory = async (
  page = 1,
  limit = 20
): Promise<{ prompts: PromptHistoryItem[]; pagination: Pagination }> => {
  const res = await axios.get<{ success: boolean; prompts: PromptHistoryItem[]; pagination: Pagination }>(
    `/api/admin/prompts?page=${page}&limit=${limit}`,
    { headers: authHeaders() }
  );
  return { prompts: res.data.prompts, pagination: res.data.pagination };
};

/**
 * GET /api/admin/prompts/:request_id
 * Detailed prompt view with cross-service lifecycle event trace.
 */
export const getPromptDetail = async (requestId: string): Promise<PromptDetailResponse> => {
  const res = await axios.get<PromptDetailResponse>(
    `/api/admin/prompts/${encodeURIComponent(requestId)}`,
    { headers: authHeaders() }
  );
  return res.data;
};

/**
 * POST /api/admin/llm/store
 * Ingests knowledge base chunks for a specific URL into the LLM Store.
 */
export const syncUrlToLLMStore = async (
  sourceUrl: string
): Promise<{ success: boolean; request_id: string; result: unknown }> => {
  const res = await axios.post<{ success: boolean; request_id: string; result: unknown }>(
    "/api/admin/llm/store",
    { source_url: sourceUrl },
    { headers: authHeaders() }
  );
  return res.data;
};

/**
 * POST /api/admin/llm/store
 * Bulk ingests all knowledge base chunks into the LLM Store.
 */
export const syncAllToLLMStore = async (): Promise<{
  success: boolean;
  request_id: string;
  total_urls: number;
  total_documents_stored: number;
}> => {
  const res = await axios.post<{
    success: boolean;
    request_id: string;
    total_urls: number;
    total_documents_stored: number;
  }>("/api/admin/llm/store", { all: true }, { headers: authHeaders() });
  return res.data;
};

/**
 * GET /api/admin/llm/health
 * Checks LLM and Qdrant connectivity.
 */
export const getLLMServiceHealth = async (): Promise<{
  success: boolean;
  llm_service: { url: string; status: unknown };
  qdrant: { status: unknown };
}> => {
  const res = await axios.get<{
    success: boolean;
    llm_service: { url: string; status: unknown };
    qdrant: { status: unknown };
  }>("/api/admin/llm/health", { headers: authHeaders() });
  return res.data;
};


// ── Destination-driven discovery ─────────────────────────────────────────────

export interface DiscoveredCandidate {
  url: string;
  title: string;
  domain: string;
  /** Trust score 0-100. Higher ranks first; unknown domains score 30. */
  score: number;
  /** Domain is curated-trusted or a government tourism board. */
  trusted: boolean;
  /** The expansion query that surfaced this URL. */
  query: string;
  /** Already present in knowledge_base. */
  already_indexed: boolean;
  last_indexed_at: string | null;
  indexed_chunks: number;
  /** Indexed, but older than the freshness window — worth re-crawling. */
  stale: boolean;
  /** What the automated path would do with this candidate, and why. */
  recommended: boolean;
  reason: string;
}

export interface DiscoverResponse {
  success: boolean;
  destination: string;
  provider: string;
  queries: string[];
  /** Raw search hits before filtering — the denominator for "kept N of M". */
  considered: number;
  candidates: DiscoveredCandidate[];
  recommended_count: number;
  /** Per-query search failures; non-empty means thinner topic coverage. */
  errors: string[];
}

export interface AutoCrawlResponse extends CrawlSubmitResponse {
  destination: string;
  /** null when nothing needed crawling — see `status: "skipped"`. */
  job_id?: string;
  urls?: string[];
  candidates?: DiscoveredCandidate[];
  detail?: string;
  errors?: string[];
}

/**
 * POST /api/admin/discover
 * Destination in, reviewable candidate URLs out. Crawls nothing.
 */
export const discoverCandidates = async (
  destination: string,
  maxUrls?: number
): Promise<DiscoverResponse> => {
  const res = await axios.post<DiscoverResponse>(
    "/api/admin/discover",
    { destination, ...(maxUrls ? { max_urls: maxUrls } : {}) },
    { headers: authHeaders() }
  );
  return res.data;
};

/**
 * POST /api/admin/crawl/auto
 *
 * Crawls a destination. Passing `urls` crawls exactly that reviewed
 * selection; omitting it crawls everything discovery recommends. Either way
 * the destination is recorded on the job, so "why was this page crawled?"
 * stays answerable afterwards.
 */
export const submitAutoCrawl = async (
  destination: string,
  options?: { urls?: string[]; maxUrls?: number; asyncMode?: boolean }
): Promise<AutoCrawlResponse> => {
  const asyncMode = options?.asyncMode ?? false;
  const res = await axios.post<AutoCrawlResponse>(
    `/api/admin/crawl/auto${asyncMode ? "?async=true" : ""}`,
    {
      destination,
      ...(options?.urls ? { urls: options.urls } : {}),
      ...(options?.maxUrls ? { max_urls: options.maxUrls } : {}),
    },
    { headers: authHeaders() }
  );
  return res.data;
};
