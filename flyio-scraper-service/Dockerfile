# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── System dependencies for Playwright / Chromium (required by crawl4ai) ──────
# crawl4ai uses Playwright's headless Chromium to render JS-heavy pages.
# These are the minimal system libs Chromium needs on a Debian-slim base.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        libnss3 \
        libatk-bridge2.0-0 \
        libdrm2 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libxkbcommon0 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium binary (crawl4ai needs this separately from
# the system Chromium installed above — Playwright manages its own binary).
RUN python -m playwright install --with-deps chromium

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 8080

# All configuration comes from environment variables / Fly secrets.
# Nothing is hardcoded in this image.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
