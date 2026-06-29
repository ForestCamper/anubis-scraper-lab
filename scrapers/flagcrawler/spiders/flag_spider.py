"""FlagSpider — the Scrapy + Playwright crawler for the Extraction Range.

Every request is fetched with a real (headless) Chromium via scrapy-playwright,
so JavaScript runs, the Anubis proof-of-work challenge is solved, and dynamic
surfaces render. For each page it harvests FLAG{...} tokens from many surfaces —
the same ones the selenium scraper covers — but expressed as a proper Scrapy
spider yielding FlagItems into the pipeline/feed.

Anubis note: scrapy-playwright shares one browser context across requests, so the
clearance cookie set while solving the seed's PoW persists. Only the seed pays
the challenge; the concurrent fan-out is pre-authorised (the same amortisation
the selenium scraper demonstrates).
"""
import asyncio
import base64
import os
import re
import time
from urllib.parse import urljoin, urlparse

import scrapy

from flagcrawler.items import FlagItem

# Marker name of the Anubis clearance cookie (proof the PoW was solved).
ANUBIS_AUTH_COOKIE = "anubis-auth"

FLAG_RE = re.compile(r"FLAG\{[A-Za-z0-9_-]+\}")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css", ".js",
            ".json", ".vtt", ".pdf", ".zip", ".woff", ".woff2", ".ttf")
# base64 blobs and data: URIs we will try to decode and re-scan.
B64_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
DATA_URI_RE = re.compile(r"data:[^;,\s]*;base64,([A-Za-z0-9+/=]+)")

# --- in-page JavaScript (Playwright evaluate) -------------------------------- #
JS_SCROLL = """() => new Promise(res => {
  let y = 0;
  const step = () => {
    window.scrollTo(0, y); y += 600;
    if (y > (document.body ? document.body.scrollHeight : 0) + 1000) { res(); }
    else { setTimeout(step, 30); }
  };
  step();
})"""

JS_STORAGE = """() => {
  const dump = s => { const o={}; for (let i=0;i<s.length;i++){const k=s.key(i);o[k]=s.getItem(k);} return o; };
  return JSON.stringify({local: dump(localStorage), session: dump(sessionStorage)});
}"""

JS_SHADOW = """() => {
  let out = [];
  const walk = root => { root.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) { out.push(el.shadowRoot.textContent); walk(el.shadowRoot); } }); };
  walk(document);
  return out.join(' \\n ');
}"""

JS_INDEXEDDB = """async () => {
  let found = [];
  try {
    const dbs = (indexedDB.databases ? await indexedDB.databases() : []);
    for (const meta of dbs) {
      await new Promise(res => {
        const req = indexedDB.open(meta.name);
        req.onsuccess = e => {
          const db = e.target.result;
          const stores = Array.from(db.objectStoreNames);
          if (!stores.length) { db.close(); return res(); }
          const tx = db.transaction(stores, 'readonly');
          let pending = stores.length;
          stores.forEach(s => {
            const all = tx.objectStore(s).getAll();
            all.onsuccess = ev => { found.push(JSON.stringify(ev.target.result)); if (--pending===0){db.close();res();} };
            all.onerror = () => { if (--pending===0){db.close();res();} };
          });
        };
        req.onerror = () => res();
      });
    }
  } catch (e) {}
  return found.join(' ');
}"""

# Fetch same-origin sub-resources from inside the page (carries the Anubis
# cookie, so it is not re-challenged): <track> caption files and any .json the
# page references (e.g. the ajax-fetch specimen's assets/ajax-data.json).
JS_FETCH_RESOURCES = """async () => {
  const urls = new Set();
  document.querySelectorAll('track[src]').forEach(t => urls.add(t.src));
  const html = document.documentElement.outerHTML;
  const re = /["'`]([^"'`]+\\.json[^"'`]*)["'`]/g; let m;
  while ((m = re.exec(html))) { try { urls.add(new URL(m[1], location.href).href); } catch (e) {} }
  let texts = [];
  for (const u of urls) { try { texts.push(await (await fetch(u)).text()); } catch (e) {} }
  return texts.join(' \\n ');
}"""

# Re-fetch the current URL from inside the page and serialise its response
# headers — same-origin fetch exposes all headers to JS, so the X-Access-Token
# header specimen is readable here.
JS_FETCH_HEADERS = """async () => {
  try {
    const r = await fetch(location.href, {cache: 'no-store'});
    let h = []; r.headers.forEach((v, k) => h.push(k + ':' + v));
    return h.join(' ');
  } catch (e) { return ''; }
}"""

# Absolute URLs to follow, read from the live (rendered) DOM.
JS_LINKS = """() => {
  const out = [];
  document.querySelectorAll('a[href]').forEach(a => out.push(a.href));
  document.querySelectorAll('iframe[src],frame[src]').forEach(f => out.push(f.src));
  return out;
}"""

# True while the Anubis interstitial is on screen (challenge element or its title).
JS_IS_ANUBIS = ("() => !!document.getElementById('anubis_challenge') "
                "|| /not a bot/i.test(document.title || '')")
JS_HAS_CHALLENGE = "() => !!document.getElementById('anubis_challenge')"


class FlagSpider(scrapy.Spider):
    name = "flags"

    def __init__(self, seed=None, ocr="0", isolate="0", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seed = seed or os.environ.get("SEED_URL", "http://anubis:8923/index.html")
        self.allowed = urlparse(self.seed).netloc
        self.ocr = str(ocr).lower() in ("1", "true", "yes", "on")
        # isolate=True: give every request its own throwaway Playwright context
        # (separate cookie jar), so each request must solve its OWN Anubis PoW —
        # as if it came from a different machine. Default: one shared context, so
        # only the seed pays the PoW (amortised).
        self.isolate = str(isolate).lower() in ("1", "true", "yes", "on")
        self._emitted = set()  # flags already yielded (avoids duplicate items/log noise)
        self._ctx_seq = 0      # monotonic counter for unique per-request context names

    # --- request construction ------------------------------------------------ #
    def _request(self, url, dont_filter=False):
        """Build a Playwright request that hands the page back to parse().

        Default (shared context): the Anubis clearance cookie is reused, so only
        the seed pays the PoW (see PLAYWRIGHT_PROCESS_REQUEST_HEADERS=None).

        isolate mode: each request gets a unique, throwaway browser context with
        its own empty cookie jar — Anubis sees an unauthenticated client every
        time, so every request runs a fresh PoW (simulating many distinct
        machines). The context is torn down in parse() so they don't accumulate.
        """
        meta = {"playwright": True, "playwright_include_page": True}
        if self.isolate:
            self._ctx_seq += 1
            meta["playwright_context"] = f"req-{self._ctx_seq}"
            meta["playwright_context_kwargs"] = {}  # fresh, isolated context
        return scrapy.Request(url, callback=self.parse, errback=self.errback,
                              meta=meta, dont_filter=dont_filter)

    async def _settle_through_anubis(self, page):
        """Block until this page is the real content, not the Anubis interstitial.

        The interstitial removes #anubis_challenge *before* the clearance cookie
        is committed and the real page loads, so waiting on that element alone
        races. Instead we wait for the `…anubis-auth` cookie to appear AND the
        challenge to be gone. No-op for pages that were never an interstitial
        (raw range, or follow pages already authorised by the shared context).
        """
        try:
            is_anubis = await page.evaluate(JS_IS_ANUBIS)
        except Exception:
            is_anubis = False
        if not is_anubis:
            return  # already real content
        deadline = time.time() + 210  # covers a difficulty-6 PoW long tail
        while time.time() < deadline:
            try:
                cookies = await page.context.cookies()
            except Exception:
                cookies = []
            authed = any(c.get("name", "").endswith(ANUBIS_AUTH_COOKIE) for c in cookies)
            if authed:
                try:
                    still = await page.evaluate(JS_HAS_CHALLENGE)
                except Exception:
                    still = False
                if not still:
                    return
            await asyncio.sleep(0.25)
        self.logger.warning("Anubis not cleared within timeout for %s", page.url)

    async def start(self):
        # Scrapy >= 2.13 entrypoint for initial requests (async generator).
        yield self._request(self.seed, dont_filter=True)

    def start_requests(self):
        # Backwards-compat entrypoint for Scrapy < 2.13.
        yield self._request(self.seed, dont_filter=True)

    # --- parsing ------------------------------------------------------------- #
    async def parse(self, response):
        page = response.meta.get("playwright_page")
        title = ""
        source = response.text          # fallback if no page (shouldn't happen)
        hrefs = []
        # (text, technique) blobs to scan for flags.
        blobs = []
        # HTTP response headers from the navigation (e.g. X-Access-Token).
        blobs.append((" ".join(f"{k.decode(errors='ignore')}:"
                               f"{b','.join(v).decode(errors='ignore')}"
                               for k, v in response.headers.items()),
                      "HTTP header"))

        if page is not None:
            try:
                # Make sure we're past Anubis before reading anything, then settle.
                await self._settle_through_anubis(page)
                try:
                    await page.evaluate(JS_SCROLL)
                    await page.wait_for_timeout(600)  # let fetch()/timers resolve
                except Exception:
                    pass
                try:
                    source = await page.content()
                except Exception:
                    source = response.text
                try:
                    title = await page.title()
                except Exception:
                    title = ""
                blobs += await self._harvest_browser(page)
                try:
                    hrefs = await page.evaluate(JS_LINKS) or []
                except Exception:
                    hrefs = []
            finally:
                await self._teardown(page)
        else:
            hrefs = response.css(
                "a::attr(href), iframe::attr(src), frame::attr(src)").getall()

        # Real (post-Anubis) page source + base64/data-URI decoding of it.
        blobs.insert(0, (source, "rendered DOM / source"))
        blobs += self._decode_blobs(source)

        # Emit one FlagItem per distinct flag, tagged with the first surface that
        # found it. Spider-level dedup keeps the item stream (and logs) clean; the
        # FlagDedupPipeline remains as a cross-run safety net.
        for text, technique in blobs:
            for flag in FLAG_RE.findall(text or ""):
                if flag in self._emitted:
                    continue
                self._emitted.add(flag)
                yield FlagItem(flag=flag, source_url=response.url,
                               page_title=title, technique=technique,
                               http_status=response.status)

        # Follow <a>/<iframe>/<frame> within scope (Scrapy's dupefilter dedups).
        for nxt in self._links(response.url, hrefs):
            yield self._request(nxt)

    async def _harvest_browser(self, page):
        """Pull flag-bearing text from browser-only surfaces via Playwright."""
        out = []

        async def grab(js, technique):
            try:
                out.append((str(await page.evaluate(js)), technique))
            except Exception:
                pass

        # rendered text, storage, shadow DOM, IndexedDB, sub-resources, headers
        await grab("() => document.body ? document.body.innerText : ''", "rendered DOM text")
        await grab(JS_STORAGE, "localStorage / sessionStorage")
        await grab(JS_SHADOW, "shadow DOM")
        await grab(JS_INDEXEDDB, "IndexedDB")
        await grab(JS_FETCH_RESOURCES, "sub-resource (track / json)")
        await grab(JS_FETCH_HEADERS, "HTTP header (in-page fetch)")

        # cookies (incl. anything the page set) via the browser context
        try:
            cookies = await page.context.cookies()
            out.append((str(cookies), "cookie"))
        except Exception:
            pass

        # iframe / frame documents
        try:
            for fr in page.frames:
                try:
                    out.append((await fr.content(), "iframe/frame source"))
                    out.append((await fr.evaluate(
                        "() => document.body ? document.body.innerText : ''"),
                        "iframe/frame text"))
                except Exception:
                    pass
        except Exception:
            pass

        if self.ocr:
            out += await self._ocr(page)
        return out

    async def _ocr(self, page):
        """Optional OCR of <canvas>/<img> pixels (needs pytesseract + pillow)."""
        try:
            import io
            from PIL import Image
            import pytesseract
        except Exception:
            self.logger.warning("ocr requested but pytesseract/pillow unavailable")
            return []
        out = []
        try:
            handles = await page.query_selector_all("canvas, img")
            for h in handles:
                try:
                    png = await h.screenshot()
                    txt = pytesseract.image_to_string(Image.open(io.BytesIO(png)))
                    out.append((txt, "OCR (pixels)"))
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def _decode_blobs(self, html):
        """Decode base64 blobs and data: URIs found in the HTML, re-scan them."""
        out = []
        for b64 in DATA_URI_RE.findall(html or ""):
            out += self._try_b64(b64, "data-URI (base64)")
        # Limit generic base64 scanning to blobs that actually decode to text
        # containing 'FLAG' to avoid noise.
        for blob in B64_RE.findall(html or ""):
            out += self._try_b64(blob, "base64-decoded")
        return out

    @staticmethod
    def _try_b64(blob, technique):
        try:
            pad = "=" * (-len(blob) % 4)
            dec = base64.b64decode(blob + pad, validate=False).decode("utf-8", "ignore")
        except Exception:
            return []
        return [(dec, technique)] if "FLAG{" in dec else []

    def _links(self, base_url, hrefs):
        out = []
        for href in hrefs:
            u = urljoin(base_url, (href or "").split("#")[0])
            if not u.startswith(("http://", "https://")):
                continue
            if urlparse(u).netloc != self.allowed:
                continue
            if u.lower().endswith(SKIP_EXT):
                continue
            out.append(u)
        return out

    async def _teardown(self, page):
        """Close the page; in isolate mode close the whole throwaway context so
        each request's cookie jar dies with it (and contexts don't pile up)."""
        if page is None:
            return
        try:
            if self.isolate:
                await page.context.close()  # also closes the page
            else:
                await page.close()
        except Exception:
            pass

    async def errback(self, failure):
        await self._teardown(failure.request.meta.get("playwright_page"))
        self.logger.warning("request failed: %s (%r)",
                            failure.request.url, failure.value)
