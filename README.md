# Anubis Scraper Lab

A self-contained Docker lab for studying how **[Anubis](https://anubis.techaro.lol/)**
— a proof-of-work (PoW) anti-bot reverse proxy — holds up against web scrapers of
increasing sophistication.

A mock website (**the extraction range**) hides **46 `FLAG{…}` tokens**, each via a
different storage/embedding technique (plain text, comments, `data-*` attributes,
base64, JSON-LD, shadow DOM, canvas pixels, IndexedDB, response headers, WebVTT
tracks, …). Anubis sits in front of it and challenges every client. Three scrapers
then try to recover the flags *through* Anubis, and we measure who gets through, how
much coverage they achieve, and what the PoW costs them.

## Architecture

```
            host :8000
                │
                ▼
        ┌───────────────┐        ┌──────────────────┐
        │    anubis      │  proxy │      range        │
        │  PoW proxy     ├───────►│  mock target site │
        │  (public)      │        │  (internal only)  │
        └───────▲────────┘        └──────────────────┘
                │ challenged traffic
        ┌───────┴────────┐
        │    scrapers     │  bs4 · selenium · scrapy+playwright
        └────────────────┘
```

Three Compose services:

- **`anubis`** — the only public entry point (host port **8000** → container `:8923`).
  Issues a PoW challenge to every request per `anubis/policies.yaml`.
- **`range`** — the mock target website (`range/site/serve.py` + static files).
  Internal only; reachable solely through Anubis.
- **`scrapers`** — a container with Python, Chromium/chromedriver (Selenium),
  Playwright's Chromium, and tesseract; runs the three crawlers + a timing probe.

## The scrapers

| script | engine | vs Anubis | typical coverage |
|---|---|---|---|
| `scraper_bs4.py` | raw HTTP (`requests` + BeautifulSoup), **no JS** | **blocked** — can't solve the PoW | ~0/46 through Anubis · ~39/46 against the raw site |
| `scraper_selenium.py` | headless Chrome | solves the PoW, harvests 10 surfaces | ~45/46 (46 with OCR) |
| `scraper_scrapy.py` | **Scrapy + Playwright** (full project, concurrent) | solves the PoW via the browser layer | ~45/46 (46 with OCR) |

Plus **`time_anubis.py`** — a reference probe that opens a single page and reports how
long the Anubis challenge takes to clear.

The Scrapy crawler is a complete Scrapy project under `scrapers/flagcrawler/`
(`FlagSpider`, `FlagItem`, dedup + manifest-scoring pipelines, an Anubis-aware
downloader middleware, tuned concurrency). Every request runs through
**scrapy-playwright** so JavaScript executes and the PoW is solved. It writes
per-flag provenance to `flags.json` (the Scrapy `FEEDS` export).

## Quick start

```bash
docker compose up --build
```

1. `range` builds and starts (internal).
2. `anubis` starts once `range` is healthy and publishes the protected site at
   **http://localhost:8000/index.html** (open it in a browser — you'll see the PoW
   challenge, then the site).
3. `scrapers` waits for Anubis, then runs `run_all.sh`: the timing probe → bs4 →
   selenium → scrapy, each scored against `manifest.json`. The container exits;
   `anubis` and `range` keep running. Stop with `Ctrl-C`, then `docker compose down`.

## Run pieces on demand

```bash
# all three scrapers + probe, with scoring
docker compose run --rm scrapers ./run_all.sh

# a single scraper
docker compose run --rm scrapers python scraper_bs4.py --manifest manifest.json
docker compose run --rm scrapers python scraper_selenium.py --manifest manifest.json
docker compose run --rm scrapers python scraper_scrapy.py --manifest manifest.json

# enable OCR (reaches 46/46 by reading the image/canvas specimens)
docker compose run --rm -e OCR=1 scrapers python scraper_scrapy.py --manifest manifest.json --ocr

# Scrapy "isolated" mode: every request gets its own throwaway browser context
# (separate cookie jar), so each one re-solves the PoW as if from a different
# machine. Scrapy runs several of these in parallel.
docker compose run --rm -e ISOLATED=1 scrapers python scraper_scrapy.py --manifest manifest.json --isolated

# point any scraper at the raw site (bypassing Anubis) or anywhere else
docker compose run --rm scrapers python scraper_scrapy.py --seed http://range:8000/index.html --manifest manifest.json
```

Inside the Compose network the scrapers reach the site through Anubis at
`http://anubis:8923` (set via `SEED_URL`); the raw site is `http://range:8000`.

## Knobs

All Anubis knobs live in `docker-compose.yml` (env) and `anubis/policies.yaml`.

- **`DIFFICULTY`** / `policies.yaml` `challenge.difficulty` — PoW difficulty (leading
  zero nibbles). Each step is ~16× more work. The in-browser solve time is
  high-variance; difficulty 4 is fast (~seconds), 6 is steep (tens of seconds).
- **`COOKIE_EXPIRATION_TIME`** — the heart of the experiment:
  - **commented out** (default 168h) → one PoW per *session*; a whole crawl
    amortizes a single solve (the realistic case).
  - **`"1s"`** → the clearance cookie dies before the next page, so **every request
    re-solves** — the cost a stateless, high-volume scraper pays. *(This is the
    committed default in this repo; comment it out for amortized behavior.)*
- **Scrapy `--isolated` / `ISOLATED=1`** — forces per-request PoW from the client
  side (one isolated browser context per request), independent of cookie lifetime.
  Pair with `CONCURRENT_REQUESTS_PER_DOMAIN = 1` in `flagcrawler/settings.py` if you
  want the simulation strictly serial.
- **`OCR` / `--ocr`** — enables the tesseract pass for the image/canvas specimens.

## What it demonstrates

- A **no-JS scraper** (bs4) is fully blocked by Anubis — it only ever sees the
  challenge page. This is the bulk of abusive crawl traffic.
- A **browser-driven scraper** (Selenium, Scrapy+Playwright) *does* get through, but
  pays a one-time PoW per session and must run a real browser.
- Anubis taxes the **session**, not the **page**: with a normal cookie a 46-page
  crawl costs about the same as one page (amortized). The `COOKIE_EXPIRATION_TIME=1s`
  and `--isolated` modes show the opposite extreme — a stateless/distributed scraper
  paying the PoW on every request.

## Layout

```
anubis-scraper-lab/
├── docker-compose.yml
├── anubis/
│   ├── Dockerfile          # FROM ghcr.io/techarohq/anubis, bakes in policies.yaml
│   └── policies.yaml       # bot policy + PoW difficulty + in-memory store
├── range/
│   ├── Dockerfile
│   └── site/               # the extraction range (index, pages/, assets/, serve.py, manifest.json)
└── scrapers/
    ├── Dockerfile          # Python + Chromium/chromedriver + Playwright + tesseract
    ├── requirements.txt
    ├── entrypoint.sh       # waits for the range, then runs the command
    ├── run_all.sh          # probe → bs4 → selenium → scrapy, with scoring
    ├── time_anubis.py      # single-page Anubis timing probe
    ├── scraper_bs4.py      # raw-HTML crawler
    ├── scraper_selenium.py # headless-Chrome crawler
    ├── scraper_scrapy.py   # launcher for the Scrapy + Playwright crawler
    ├── scrapy.cfg
    ├── flagcrawler/        # the Scrapy project (spiders / items / pipelines / settings / middlewares)
    └── manifest.json       # answer key for scoring
```

## Notes

- The Anubis image is distroless and runs as a non-root user, so it has no shell and
  cannot create a writable `/data` at build time — the policy therefore uses the
  in-memory store (`store.backend: memory`). For persistence, mount a host-writable
  volume at `/data` (owned by uid 1000) and switch to the bbolt backend.
- `shm_size: 1gb` is set on the `scrapers` service — headless Chromium needs the
  shared memory; the scripts also pass `--disable-dev-shm-usage`.
- The `ED25519_PRIVATE_KEY_HEX` in `docker-compose.yml` is a throwaway key for this
  local lab, not a secret.
