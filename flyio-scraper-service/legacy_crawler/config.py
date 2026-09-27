"""
Travel pipeline config — exactly 6 sources, Crawl4AI + ChromaDB settings.

Two crawl strategies only:
  "mediawiki_api" -> crawler/wikivoyage_api.py   (official API, no scraping)
  "crawl4ai"      -> crawler/crawl4ai_crawler.py (headless browser crawl,
                      falls back to crawler/resilience.py on failure)

No per-site CSS selectors here on purpose — Crawl4AI's own content
extraction (readability-style boilerplate removal) replaces the old
hand-written ".entry-content" / ".post-content" selector lists.
"""

SOURCES = [
    {
        "name": "Wikivoyage",
        "strategy": "mediawiki_api",
        "api_base": "https://en.wikivoyage.org/w/api.php",
        "seed_titles": ["India"],
        "max_pages": 25,
    },
    {
        "name": "TourMyIndia",
        "strategy": "crawl4ai",
        "start_urls": ["https://www.tourmyindia.com/"],
        "allowed_domain": "www.tourmyindia.com",
        "max_pages": 20,
    },
    {
        "name": "Holidify",
        "strategy": "crawl4ai",
        "start_urls": ["https://www.holidify.com/"],
        "allowed_domain": "www.holidify.com",
        "max_pages": 20,
    },
    {
        "name": "Thrillophilia",
        "strategy": "crawl4ai",
        "start_urls": ["https://www.thrillophilia.com/"],
        "allowed_domain": "www.thrillophilia.com",
        "max_pages": 20,
    },
    {
        "name": "TravelTriangle",
        "strategy": "crawl4ai",
        "start_urls": ["https://traveltriangle.com/"],
        "allowed_domain": "traveltriangle.com",
        "max_pages": 20,
    },
    {
        "name": "IncredibleIndia",
        "strategy": "crawl4ai",
        "start_urls": ["https://www.incredibleindia.gov.in/en"],
        "allowed_domain": "www.incredibleindia.gov.in",
        "max_pages": 20,
    },
]

# ── User agents (shared by crawl4ai + the resilience fallback layer) ──────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

# ── Crawl politeness (used by the requests fallback + robots checks) ──────
REQUEST_DELAY_SECONDS = 2.0
REQUEST_DELAY_JITTER  = 1.0
REQUEST_TIMEOUT       = 20
MAX_RETRIES           = 4
BACKOFF_MULTIPLIER    = 2
ROTATE_USER_AGENTS    = True
RESPECT_ROBOTS_TXT    = True
RETRY_STATUS_CODES    = {429, 500, 502, 503, 504}

# ── Crawl4AI settings ───────────────────────────────────────────────────────
CRAWL4AI_HEADLESS        = True
CRAWL4AI_PAGE_TIMEOUT_MS = 45000
CRAWL4AI_WAIT_UNTIL      = "domcontentloaded"
CRAWL4AI_MAX_CONCURRENT  = 3

# ── Chunking (H2-based section chunking) ────────────────────────────────────
MAX_CHUNK_CHARS     = 1800
CHUNK_OVERLAP_CHARS = 200
CHUNK_HEADING_LEVEL = 2     # flush a new chunk at H1/H2, not H3+

# ── ChromaDB / embeddings ───────────────────────────────────────────────────
CHROMA_PERSIST_DIR    = "chroma_db"
CHROMA_COLLECTION_NAME = "travel_india"
EMBEDDING_MODEL_NAME  = "all-MiniLM-L6-v2"   # sentence-transformers, free, offline

# ── Frontier filtering ──────────────────────────────────────────────────
# Utility/legal/marketing pages that show up on every site's internal
# links but never contain travel content — skip enqueuing these so crawl
# budget (max_pages) goes to actual destination/guide pages instead.
EXCLUDE_URL_PATTERNS = [
    "account", "login", "signin", "signup", "register", "bookmark",
    "privacy-policy", "terms-of-use", "terms-and-conditions", "cookie-policy",
    "contact-us", "contact", "faqs", "faq", "sitemap",
    "press-release", "testimonial", "career", "jobs",
    "travel-leads", "aboutus", "about-us", "affiliate", "advertise",
]

OUTPUT_DIR = "output"

# ── Crawler v2 Constants ───────────────────────────────────────────────────
WIKIVOYAGE_CITIES = [
    "Delhi", "Jaipur", "Agra", "Mumbai", "Bengaluru", "Goa", "Udaipur", "Varanasi",
    "Kochi", "Darjeeling", "Manali", "Shimla", "Ooty", "Munnar", "Rishikesh",
    "Amritsar", "Hyderabad", "Chennai", "Kolkata", "Srinagar", "Hampi", "Jaisalmer",
    "Mysore", "Leh", "Pondicherry", "Alappuzha", "Jodhpur"
]

USER_AGENT = "TravelKB/1.0 (kurianjose005@gmail.com) requests/2.31"
RAW_CACHE_DIR = "raw_cache"

