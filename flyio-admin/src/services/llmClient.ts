import axios from "axios";
import { env } from "../config/env";

/**
 * HTTP client for flyio-ai-llm microservice.
 *
 * All configuration (base URL, service API key) read from environment variables — nothing hardcoded.
 * Authenticates via the 'X-Service-API-Key' header on all /v1/* routes as defined in the LLM microservice contract.
 */

const llmHttp = axios.create({
  baseURL: env.LLM_SERVICE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 300_000, // 5 minutes for LLM generation/vector searches and large store requests
});

llmHttp.interceptors.request.use((config) => {
  // env.ts requires this key and refuses to start without it, so there is
  // nothing to fall back to here. Note that /v1/health and /health are public
  // on the LLM service while /v1/api/* is not — a healthy connectivity check
  // says nothing about whether this key is valid.
  config.headers["X-Service-API-Key"] = env.LLM_SERVICE_API_KEY;
  return config;
});

export interface LLMGenerateRequest {
  request_id: string;
  prompt: string;
  metadata?: Record<string, unknown>;
}

export interface LLMGenerateResponse {
  success: boolean;
  request_id: string;
  status: "data_found" | "data_required" | "generation_failed" | string;
  data_found?: boolean;
  data_required?: boolean;
  results?: Array<{
    id?: string;
    score?: number;
    payload?: Record<string, unknown>;
    text?: string;
  }>;
  plan?: Record<string, unknown> | null;
  message?: string;
  metadata?: Record<string, unknown>;
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
}

export interface LLMDocumentItem {
  text: string;
  metadata: Record<string, unknown>;
  source_url?: string;
  /**
   * Chunk fields sent at the top level as well as inside `metadata`.
   *
   * flyio-ai-llm's StoreDocumentItem reads these from the top level and
   * only falls back to `metadata` for a subset of them, so sending them
   * here is what the contract actually asks for — nesting alone relies on
   * that service's compatibility shim. `content_html` in particular was
   * never sent at all, so every point ingested from the knowledge base
   * landed in Qdrant with a null content_html.
   */
  title?: string;
  section_path?: string;
  chunk_index?: number;
  content_html?: string;
  /**
   * True chunk count for the source page. Only needed when one page is split
   * across several store calls — the LLM service otherwise infers the total
   * from the siblings present in a single request, which undercounts once
   * Admin batches. See pushToLlmStore.
   */
  total_chunks?: number;
}

export interface LLMStoreRequest {
  request_id: string;
  documents: LLMDocumentItem[];
  mode?: "pre_chunked" | "auto";
}

export interface LLMStoreResponse {
  success: boolean;
  request_id: string;
  stored_count?: number;
  /** Qdrant point IDs of the stored points, in the order documents were sent. */
  document_ids?: string[];
  collection_name?: string;
  message?: string;
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
}

export interface LLMHealthResponse {
  status: string;
  service?: string;
  version?: string;
  environment?: string;
  timestamp?: string;
  request_id?: string;
}

export interface LLMQdrantHealthResponse {
  status: string;
  connected: boolean;
  qdrant_url?: string;
  collection_name?: string;
  collection_exists?: boolean;
  vector_size?: number;
  details?: string;
}

/**
 * Calls LLM Generate / Retrieval endpoint.
 * POST /v1/api/generate
 */
export async function generatePlan(
  requestId: string,
  prompt: string,
  metadata?: Record<string, unknown>
): Promise<LLMGenerateResponse> {
  const response = await llmHttp.post<LLMGenerateResponse>("/v1/api/generate", {
    request_id: requestId,
    prompt,
    metadata: {
      source: "flyio-admin",
      ...metadata,
    },
  });
  return response.data;
}

/**
 * Calls LLM Store API for vector database ingestion.
 * POST /v1/api/store
 */
export async function storeDocuments(
  requestId: string,
  documents: LLMDocumentItem[],
  mode: "pre_chunked" | "auto" = "pre_chunked"
): Promise<LLMStoreResponse> {
  try {
    const response = await llmHttp.post<LLMStoreResponse>("/v1/api/store", {
      request_id: requestId,
      documents,
      mode,
    });
    return response.data;
  } catch (err: unknown) {
    // An axios error's `message` is just "Request failed with status code 422",
    // which says nothing about which document or field the LLM service
    // rejected. Callers log and surface that message, so fold the response
    // body into it rather than making every ingestion failure a trip to the
    // container logs.
    if (axios.isAxiosError(err) && err.response) {
      const body = typeof err.response.data === "string"
        ? err.response.data
        : JSON.stringify(err.response.data);
      throw new Error(
        `LLM Store API responded ${err.response.status}: ${body?.slice(0, 1500)}`
      );
    }
    throw err;
  }
}

export interface LLMServiceKeyCheck {
  valid: boolean;
  detail: string;
}

/**
 * Verifies that the configured service key is actually accepted.
 *
 * The health endpoints are deliberately public on the LLM service
 * (/health and /v1/health), so a green connectivity check proves only that
 * the service is reachable — it says nothing about the key, and this panel
 * reported "healthy" through an entire outage where every /v1/api call was
 * being rejected with a 401.
 *
 * There is no dedicated whoami route to call, so this issues a GET against a
 * POST-only /v1/api path: the auth middleware runs before routing, so a 401
 * means the key was rejected while a 405 means it was accepted and the
 * request only then failed to match a method. Nothing is created or read.
 *
 * A key is reported valid only on a positive answer from the application
 * itself. Anything else — a transport failure, or a 5xx from the proxy in
 * front of a host that is not the LLM service — is reported as a failure
 * naming LLM_SERVICE_URL, because in those cases the key was never tested.
 */
export async function checkServiceKey(): Promise<LLMServiceKeyCheck> {
  let status: number;
  try {
    const probe = await llmHttp.get("/v1/api/store", { validateStatus: () => true });
    status = probe.status;
  } catch (err: unknown) {
    const e = err as Error;
    return {
      valid: false,
      detail:
        `Could not reach the LLM service at ${env.LLM_SERVICE_URL}: ${e.message}. ` +
        "Check LLM_SERVICE_URL before suspecting the key.",
    };
  }

  if (status === 401) {
    return {
      valid: false,
      detail:
        "The LLM service rejected LLM_SERVICE_API_KEY. It must equal SERVICE_API_KEY in " +
        "the flyio-ai-llm environment. Note this is a different key from the scraper's — " +
        "SCRAPER_SERVICE_API_KEY is a separate pair and must not be reused here.",
    };
  }

  // A 5xx did not come from the application: the guarded route is reached
  // through a proxy, and a misrouted or unconfigured host answers there with
  // its own error. Treating "not a 401" as success reported a valid key while
  // LLM_SERVICE_URL pointed at a host that returned 525 and served nothing at
  // all — the exact misconfiguration this check exists to catch. Auth has only
  // demonstrably run when the application itself answers.
  if (status >= 500) {
    return {
      valid: false,
      detail:
        `${env.LLM_SERVICE_URL}/v1/api/store answered ${status}, which is not the LLM ` +
        "service replying. Check that LLM_SERVICE_URL points at the right host; the key " +
        "was never actually tested.",
    };
  }

  // Auth runs before routing, so any application-level answer to this GET on a
  // POST-only route (405 in practice) means the key was accepted.
  return { valid: true, detail: "LLM_SERVICE_API_KEY accepted by the LLM service." };
}

/**
 * Checks LLM Service health.
 * GET /v1/health or GET /health
 */
export async function getLLMHealth(): Promise<LLMHealthResponse> {
  try {
    const response = await llmHttp.get<LLMHealthResponse>("/v1/health");
    return response.data;
  } catch {
    const fallback = await llmHttp.get<LLMHealthResponse>("/health");
    return fallback.data;
  }
}

/**
 * Checks Qdrant connectivity through LLM service.
 * GET /v1/health/qdrant or GET /health/qdrant
 */
export async function getQdrantHealth(): Promise<LLMQdrantHealthResponse> {
  try {
    const response = await llmHttp.get<LLMQdrantHealthResponse>("/v1/health/qdrant");
    return response.data;
  } catch {
    const fallback = await llmHttp.get<LLMQdrantHealthResponse>("/health/qdrant");
    return fallback.data;
  }
}
