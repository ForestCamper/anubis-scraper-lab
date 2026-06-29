"""Scrapy settings for the flag crawler.

This crawler drives a real browser through scrapy-playwright so it can execute
JavaScript, solve the Anubis proof-of-work challenge, and harvest dynamic
surfaces (storage, shadow DOM, etc.) — while still being a fully idiomatic
Scrapy project (spiders / items / pipelines / middlewares).
"""

BOT_NAME = "flagcrawler"
SPIDER_MODULES = ["flagcrawler.spiders"]
NEWSPIDER_MODULE = "flagcrawler.spiders"

# --- scrapy-playwright requires the asyncio reactor --------------------------
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
}
# Anubis at difficulty 6 is a slow, high-variance PoW (~80s, with a long tail),
# so allow plenty of navigation/wait headroom.
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 200_000  # ms

# CRITICAL for Anubis cookie reuse: scrapy-playwright's default header handling
# (use_scrapy_headers) rewrites each navigation's headers from the Scrapy
# request, which DROPS the browser context's Cookie — so the Anubis clearance
# cookie would never be sent and every page would re-run the PoW. None = let the
# browser send its own headers (incl. the context cookie), so the seed solves the
# PoW once and the shared context reuses the cookie for the rest of the crawl.
PLAYWRIGHT_PROCESS_REQUEST_HEADERS = None

# --- Concurrency -------------------------------------------------------------
# Scrapy is asynchronous (single-threaded Twisted reactor), not thread-based; we
# honour the "multi-threaded requests" intent through high request concurrency.
# Each in-flight request holds an open Playwright tab, so we keep this moderate
# (the scrapers service is given shm_size: 1gb in docker-compose for headless
# Chromium). Raise CONCURRENT_REQUESTS for a more aggressive crawl.
CONCURRENT_REQUESTS = 12
# Only the seed pays the Anubis PoW; the shared browser context then reuses the
# clearance cookie, so the fan-out is pre-authorised and safe to run in parallel.
# (Caveat: under the COOKIE_EXPIRATION_TIME=1s "mass scraping" simulation every
# page re-challenges, and Anubis clears the shared cookie on each challenge, so
# parallel requests thrash — drop this to 1 if you run that simulation.)
CONCURRENT_REQUESTS_PER_DOMAIN = 8
DOWNLOAD_DELAY = 0
AUTOTHROTTLE_ENABLED = False

# We are deliberately testing Anubis; do not let robots.txt gate the crawl.
ROBOTSTXT_OBEY = False

# Let the Playwright browser context own cookies. Scrapy's CookiesMiddleware
# never sees the Anubis clearance cookie (it is set in-browser while solving the
# PoW), and with it enabled scrapy-playwright syncs Scrapy's empty jar over the
# context — wiping that cookie and forcing every page to re-challenge. Disabling
# it lets the single shared browser context keep the cookie, so only the seed
# pays the PoW and the fan-out is pre-authorised.
COOKIES_ENABLED = False

RETRY_ENABLED = True
RETRY_TIMES = 2
DOWNLOAD_TIMEOUT = 210

# --- Pipelines & middlewares -------------------------------------------------
ITEM_PIPELINES = {
    "flagcrawler.pipelines.FlagDedupPipeline": 100,
    "flagcrawler.pipelines.ManifestScoringPipeline": 200,
}
DOWNLOADER_MIDDLEWARES = {
    "flagcrawler.middlewares.AnubisAwareMiddleware": 543,
}

# Structured output: full per-flag provenance (flag, url, technique, ...).
FEEDS = {
    "flags.json": {"format": "json", "overwrite": True, "indent": 2},
}

# Quieter, predictable logs; the launcher overrides LOG_LEVEL for --quiet.
LOG_LEVEL = "INFO"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TELNETCONSOLE_ENABLED = False

# MANIFEST_PATH is injected by the launcher (scraper_scrapy.py --manifest ...).
MANIFEST_PATH = None
