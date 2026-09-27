import { query } from "../db/pgPool";
import type { DiscoveredUrl } from "./scraperClient";

/**
 * How long a crawled URL is considered current. Past this, an already-indexed
 * URL is offered for re-crawling instead of being skipped — destination pages
 * change (prices, timings, transport), and the store has no other mechanism
 * for noticing.
 */
export const KB_FRESHNESS_DAYS = 90;

export interface AnnotatedCandidate extends DiscoveredUrl {
  /** Already present in knowledge_base, under this URL or an equivalent one. */
  already_indexed: boolean;
  /**
   * The exact URL the page is stored under, when indexed. May differ from
   * `url`: discovery returns canonical URLs, while knowledge_base keeps what
   * was originally crawled (e.g. with a tracking parameter still attached).
   */
  indexed_url: string | null;
  /** Last ingest time, ISO 8601, or null if never indexed. */
  last_indexed_at: string | null;
  /** Chunks currently held for this page. */
  indexed_chunks: number;
  /** Indexed, but older than KB_FRESHNESS_DAYS. */
  stale: boolean;
  /**
   * What the automated path would do with this candidate, and why. Surfaced
   * so an operator can see the filter's reasoning rather than a bare list.
   */
  recommended: boolean;
  reason: string;
}

// Mirrors the scraper's filters.canonicalize_url. Both sides of every
// comparison here go through *this* function, so exact parity with the
// Python is not required for correctness — only that equivalent URLs agree.
const TRACKING_PARAMS = new Set([
  "fbclid", "gclid", "dclid", "msclkid", "igshid", "mkt_tok",
  "ref", "referrer", "source", "src", "campaign", "spm",
]);
const TRACKING_PREFIXES = ["utm_", "ga_", "_hs", "mc_"];

/**
 * Reduces a URL to a stable identity: lowercased scheme and host, default
 * port, fragment and tracking parameters dropped, no trailing slash on a
 * non-root path, remaining parameters sorted. Returns the input unchanged if
 * it does not parse.
 */
export function canonicalizeUrl(raw: string): string {
  let u: URL;
  try {
    u = new URL(raw);
  } catch {
    return raw;
  }
  // WHATWG URL already lowercases scheme and host and drops default ports.
  u.hash = "";
  const kept = [...u.searchParams.entries()]
    .filter(([k]) => {
      const key = k.toLowerCase();
      return !TRACKING_PARAMS.has(key) && !TRACKING_PREFIXES.some((p) => key.startsWith(p));
    })
    .sort(([a, av], [b, bv]) => (a === b ? av.localeCompare(bv) : a.localeCompare(b)));
  u.search = "";
  for (const [k, v] of kept) u.searchParams.append(k, v);
  if (u.pathname.length > 1 && u.pathname.endsWith("/")) {
    u.pathname = u.pathname.replace(/\/+$/, "") || "/";
  }
  return u.toString();
}

/** The URL to submit when crawling a candidate. */
export function crawlUrlFor(c: AnnotatedCandidate): string {
  // Re-crawling a stale page must go out under the URL it is stored as:
  // ingestion replaces rows by exact source_url (jobScheduler.storeResults),
  // and the vector store derives point IDs from it. Crawling the canonical
  // form instead would add a second copy beside the old one in both.
  return c.indexed_url ?? c.url;
}

/**
 * Marks discovery candidates with what the knowledge base already holds.
 *
 * The scraper service is stateless by design and cannot answer this — the
 * `knowledge_base` table lives here. Doing the check before crawling is what
 * stops the same page being fetched, chunked and embedded twice.
 *
 * Matching is by canonical URL, not by exact string. knowledge_base keeps
 * each page under whatever URL it was first crawled as, and a page pasted
 * with "?utm_source=newsletter" is the same page discovery later returns
 * without it; an exact comparison called that page new, recommended it, and
 * crawled a second copy. Rows are fetched per host, then canonicalised here,
 * since the equivalence cannot be expressed as an index lookup.
 */
export async function annotateWithIndexState(
  candidates: DiscoveredUrl[]
): Promise<AnnotatedCandidate[]> {
  if (candidates.length === 0) return [];

  const hosts = [
    ...new Set(
      candidates
        .map((c) => {
          try {
            return new URL(c.url).hostname.toLowerCase();
          } catch {
            return "";
          }
        })
        .filter(Boolean)
    ),
  ];

  const indexed = hosts.length
    ? await query(
        `SELECT source_url,
                MAX(created_at) AS last_indexed_at,
                COUNT(*)        AS chunks
         FROM knowledge_base
         WHERE split_part(lower(split_part(source_url, '/', 3)), ':', 1) = ANY($1::text[])
         GROUP BY source_url`,
        [hosts]
      )
    : { rows: [] as Array<Record<string, unknown>> };

  // If several stored variants share one canonical form (duplicates from
  // before this matching existed), the most recently indexed one wins: it
  // is the copy a re-crawl should refresh.
  const state = new Map<string, { storedUrl: string; lastIndexedAt: Date; chunks: number }>();
  for (const row of indexed.rows) {
    const storedUrl = String(row.source_url);
    const lastIndexedAt = new Date(row.last_indexed_at as string);
    const key = canonicalizeUrl(storedUrl);
    const prev = state.get(key);
    if (!prev || lastIndexedAt > prev.lastIndexedAt) {
      state.set(key, { storedUrl, lastIndexedAt, chunks: parseInt(String(row.chunks), 10) });
    }
  }

  const staleBefore = Date.now() - KB_FRESHNESS_DAYS * 24 * 60 * 60 * 1000;

  return candidates.map((c) => {
    const existing = state.get(canonicalizeUrl(c.url));
    const stale = existing ? existing.lastIndexedAt.getTime() < staleBefore : false;

    let recommended: boolean;
    let reason: string;
    if (existing && !stale) {
      recommended = false;
      reason = `Already indexed (${existing.chunks} chunks)`;
    } else if (existing && stale) {
      recommended = true;
      reason = `Indexed over ${KB_FRESHNESS_DAYS} days ago — re-crawl`;
    } else if (c.trusted) {
      recommended = true;
      reason = `Trusted source (${c.domain})`;
    } else {
      // Deliberately surfaced rather than dropped: an unknown domain may be
      // exactly the right source for a small destination, and that judgement
      // is the operator's. Listed, but never auto-crawled.
      recommended = false;
      reason = "Unrecognised domain — review before crawling";
    }

    return {
      ...c,
      already_indexed: Boolean(existing),
      indexed_url: existing ? existing.storedUrl : null,
      last_indexed_at: existing ? existing.lastIndexedAt.toISOString() : null,
      indexed_chunks: existing ? existing.chunks : 0,
      stale,
      recommended,
      reason,
    };
  });
}
