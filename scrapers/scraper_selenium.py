#!/usr/bin/env python3
"""
scraper_selenium.py  —  the thorough crawler.

Drives a real (headless) Chrome with Selenium, so it sees the page the way a
browser does: JavaScript runs, dynamic content renders, storage fills, captions
load. For every page it visits it harvests FLAG{...} tokens from *many* surfaces,
not just the HTML source:

    1. rendered DOM text      (document.body.innerText, after scroll + settle)
       -> js-rendered, lazy-load, html-entities, base64 (auto-decoded slot),
          ajax/fetch, css ::after / var() / attr() once painted
    2. full serialized DOM    (outerHTML)  -> attributes, comments, inline scripts
    3. localStorage / sessionStorage
    4. cookies
    5. IndexedDB object stores
    6. Shadow DOM (pierced)
    7. <iframe> / <frame> documents (switched into, incl. data: URIs)
    8. <track> WebVTT caption files (fetched same-origin)
    9. HTTP response headers (X-Access-Token, via a side requests.get)
   10. OCR of <canvas> and <img> pixels        (optional: needs pytesseract)

It crawls recursively, following <a>, <iframe> and <frame> links, and remembers
visited URLs. Each flag is reported with the METHOD that recovered it, so you can
see why this crawler beats the BeautifulSoup one on the encoded / dynamic / stored
specimens.

Requirements:
    pip install selenium requests
    # Chrome/Chromium installed; Selenium 4.6+ auto-manages the driver.
    # optional, only for the image/canvas specimens:
    pip install pytesseract pillow      # plus the tesseract binary on your PATH

Usage:
    python3 scraper_selenium.py
    python3 scraper_selenium.py --seed http://localhost:8000/index.html --ocr
    python3 scraper_selenium.py --manifest ../scraper-test-range/manifest.json --headful
"""
import argparse
import os
import re
import time
from collections import deque
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

FLAG_RE = re.compile(r"FLAG\{[A-Za-z0-9_-]+\}")
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css", ".js",
            ".json", ".vtt", ".pdf", ".zip", ".woff", ".woff2", ".ttf")


# --- JavaScript snippets run inside the page ------------------------------- #
JS_STORAGE = """
const dump = s => { const o={}; for (let i=0;i<s.length;i++){const k=s.key(i);o[k]=s.getItem(k);} return o; };
return {local: dump(localStorage), session: dump(sessionStorage)};
"""

JS_SHADOW = """
let out = [];
const walk = root => {
  root.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) { out.push(el.shadowRoot.textContent); walk(el.shadowRoot); }
  });
};
walk(document);
return out.join(' \\n ');
"""

JS_INDEXEDDB = """
const cb = arguments[arguments.length - 1];
(async () => {
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
            all.onsuccess = ev => {
              found.push(JSON.stringify(ev.target.result));
              if (--pending === 0) { db.close(); res(); }
            };
            all.onerror = () => { if (--pending === 0) { db.close(); res(); } };
          });
        };
        req.onerror = () => res();
      });
    }
  } catch (e) {}
  cb(found.join(' '));
})();
"""

JS_FETCH_TRACKS = """
const cb = arguments[arguments.length - 1];
(async () => {
  const srcs = Array.from(document.querySelectorAll('track[src]')).map(t => t.src);
  let texts = [];
  for (const s of srcs) {
    try { texts.push(await (await fetch(s)).text()); } catch (e) {}
  }
  cb(texts.join(' \\n '));
})();
"""

JS_LINKS = """
const hrefs = Array.from(document.querySelectorAll('a[href]')).map(a => a.href);
const frames = Array.from(document.querySelectorAll('iframe[src],frame[src]')).map(f => f.src);
return {hrefs, frames};
"""


def in_scope(url, root):
    u, r = urlparse(url), urlparse(root)
    return u.scheme in ("http", "https") and u.netloc == r.netloc


def add_flags(store, text, url, method):
    """Record every flag in `text`, tagging the method that surfaced it."""
    if not text:
        return
    for f in FLAG_RE.findall(text):
        rec = store.setdefault(f, {"urls": set(), "methods": set()})
        rec["urls"].add(url)
        rec["methods"].add(method)


def make_driver(headful=False):
    opts = Options()
    if not headful:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1400")
    opts.add_argument("--disable-gpu")
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        opts.binary_location = chrome_bin

    remote = os.environ.get("SELENIUM_REMOTE_URL")  # e.g. http://chromium:4444/wd/hub
    if remote:
        driver = webdriver.Remote(command_executor=remote, options=opts)
    else:
        driver_bin = os.environ.get("CHROMEDRIVER_BIN")  # e.g. /usr/bin/chromedriver
        if driver_bin:
            from selenium.webdriver.chrome.service import Service
            driver = webdriver.Chrome(service=Service(executable_path=driver_bin), options=opts)
        else:
            driver = webdriver.Chrome(options=opts)  # Selenium Manager auto-provisions
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(15)
    return driver


def wait_past_anubis(driver, timeout=180, verbose=True):
    """If Anubis served its proof-of-work interstitial, wait for the browser to
    solve it (Anubis runs the PoW automatically in JS) and reload into the real
    page. The interstitial is identified by its unique '#anubis_challenge'
    element, which the real page does not have. No-op for non-Anubis pages, so
    this is safe to call on every navigation.
    """
    def cleared(d):
        try:
            return d.execute_script(
                "return !document.getElementById('anubis_challenge')")
        except Exception:
            return True  # mid-navigation / no DOM yet — treat as cleared, retry next tick

    try:
        if cleared(driver):
            return  # not an Anubis challenge page
        if verbose:
            print("    … Anubis challenge detected — solving PoW, waiting for clearance")
        WebDriverWait(driver, timeout).until(cleared)
    except Exception:
        if verbose:
            print(f"    ! Anubis challenge not cleared within {timeout}s")


def settle_and_scroll(driver, settle=0.6):
    """Wait for readyState complete, then scroll in steps to trigger lazy loaders."""
    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.execute_script("return document.readyState") == "complete")
    except Exception:
        pass
    try:
        h = driver.execute_script("return document.body ? document.body.scrollHeight : 0") or 0
        for y in range(0, int(h) + 1000, 600):
            driver.execute_script("window.scrollTo(0, arguments[0]);", y)
            time.sleep(0.05)
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass
    time.sleep(settle)  # let fetch()/timers resolve


def harvest_frames(driver, url, flags, depth=0):
    """Recursively switch into iframes/frames and harvest their text + source."""
    if depth > 3:
        return
    try:
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
    except Exception:
        frames = []
    for i in range(len(frames)):
        try:
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            driver.switch_to.frame(frames[i])
            try:
                add_flags(flags, driver.execute_script(
                    "return document.body ? document.body.innerText : ''"),
                    url, "iframe/frame text")
                add_flags(flags, driver.page_source, url, "iframe/frame source")
            except Exception:
                pass
            harvest_frames(driver, url, flags, depth + 1)
        except Exception:
            pass
        finally:
            driver.switch_to.default_content()


def maybe_ocr(driver, url, flags):
    """Optional: OCR every <canvas> and <img> on the page."""
    try:
        import base64 as _b64, io
        from PIL import Image
        import pytesseract
    except Exception:
        print("  (ocr requested but pytesseract/PIL unavailable — skipping)")
        return
    # canvases -> toDataURL
    pngs = []
    try:
        pngs += driver.execute_script(
            "return Array.from(document.querySelectorAll('canvas'))"
            ".map(c => { try { return c.toDataURL('image/png'); } catch(e){ return null; } })"
            ".filter(Boolean);") or []
    except Exception:
        pass
    # <img> -> draw onto a canvas to read pixels
    try:
        pngs += driver.execute_async_script("""
        const cb = arguments[arguments.length-1];
        (async () => {
          const out = [];
          for (const img of document.querySelectorAll('img')) {
            try {
              const r = await fetch(img.src); const b = await r.blob();
              const bmp = await createImageBitmap(b);
              const cv = document.createElement('canvas');
              cv.width = bmp.width; cv.height = bmp.height;
              cv.getContext('2d').drawImage(bmp, 0, 0);
              out.push(cv.toDataURL('image/png'));
            } catch(e) {}
          }
          cb(out);
        })();""") or []
    except Exception:
        pass
    for d in pngs:
        try:
            raw = _b64.b64decode(d.split(",", 1)[1])
            txt = pytesseract.image_to_string(Image.open(io.BytesIO(raw)))
            add_flags(flags, txt, url, "OCR (pixels)")
        except Exception:
            pass


def crawl(seed, headful=False, ocr=False, max_pages=10_000, verbose=True):
    flags = {}
    seen = {seed}
    queue = deque([seed])
    driver = make_driver(headful=headful)
    session = requests.Session()
    n = 0
    try:
        while queue and n < max_pages:
            url = queue.popleft()
            try:
                driver.get(url)
            except Exception as e:
                if verbose:
                    print(f"  ! skip {url} ({e.__class__.__name__})")
                continue
            n += 1
            wait_past_anubis(driver, verbose=verbose)
            settle_and_scroll(driver)

            before = len(flags)
            # 1/2 rendered text + full source
            try:
                add_flags(flags, driver.execute_script(
                    "return document.body ? document.body.innerText : ''"),
                    url, "rendered DOM text")
            except Exception:
                pass
            add_flags(flags, driver.page_source, url, "page source")
            # 3 storage
            try:
                st = driver.execute_script(JS_STORAGE)
                add_flags(flags, str(st.get("local")), url, "localStorage")
                add_flags(flags, str(st.get("session")), url, "sessionStorage")
            except Exception:
                pass
            # 4 cookies
            try:
                add_flags(flags, str(driver.get_cookies()), url, "cookie")
            except Exception:
                pass
            # 5 IndexedDB
            try:
                add_flags(flags, driver.execute_async_script(JS_INDEXEDDB), url, "IndexedDB")
            except Exception:
                pass
            # 6 shadow DOM
            try:
                add_flags(flags, driver.execute_script(JS_SHADOW), url, "shadow DOM")
            except Exception:
                pass
            # 7 iframes / frames
            harvest_frames(driver, url, flags)
            # 8 webvtt tracks
            try:
                add_flags(flags, driver.execute_async_script(JS_FETCH_TRACKS), url, "WebVTT track")
            except Exception:
                pass
            # 9 response headers (side request).
            # Carry the browser's cookies (incl. the Anubis clearance cookie) and
            # a browser-like User-Agent so this raw request also passes Anubis;
            # otherwise it just gets the PoW interstitial and the header flag is lost.
            try:
                for c in driver.get_cookies():
                    session.cookies.set(c["name"], c["value"], domain=c.get("domain"),
                                        path=c.get("path", "/"))
                ua = driver.execute_script("return navigator.userAgent")
                headers = {"User-Agent": ua} if ua else {}
                h = session.get(url, timeout=10, headers=headers).headers
                add_flags(flags, " ".join(f"{k}:{v}" for k, v in h.items()), url, "HTTP header")
            except Exception:
                pass
            # 10 optional OCR
            if ocr:
                maybe_ocr(driver, url, flags)

            gained = len(flags) - before
            if verbose:
                print(f"[{n:>3}] {url}" + (f"  <-- +{gained} new flag(s)" if gained else ""))

            # discover links (anchors + frame srcs)
            try:
                links = driver.execute_script(JS_LINKS)
            except Exception:
                links = {"hrefs": [], "frames": []}
            for nxt in (links.get("hrefs", []) + links.get("frames", [])):
                nxt, _ = urldefrag(urljoin(url, nxt))
                if not in_scope(nxt, seed) or nxt.lower().endswith(SKIP_EXT):
                    continue
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    finally:
        driver.quit()
    return flags, n


def main():
    ap = argparse.ArgumentParser(description="Thorough Selenium flag crawler.")
    ap.add_argument("--seed", default=os.environ.get("SEED_URL", "http://localhost:8000/index.html"))
    ap.add_argument("--headful", action="store_true", help="show the browser window")
    ap.add_argument("--ocr", action="store_true", help="OCR canvas/img (needs pytesseract)")
    ap.add_argument("--max-pages", type=int, default=10_000)
    ap.add_argument("--manifest", help="path to manifest.json to score coverage")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    flags, n = crawl(args.seed, headful=args.headful, ocr=args.ocr,
                     max_pages=args.max_pages, verbose=not args.quiet)
    dt = time.time() - t0

    print("\n" + "=" * 70)
    print(f"crawled {n} pages in {dt:.1f}s — found {len(flags)} distinct flag(s)")
    print("=" * 70)
    for f in sorted(flags):
        methods = ", ".join(sorted(flags[f]["methods"]))
        print(f"  {f:<34} via {methods}")

    if args.manifest:
        import json
        expected = {s["flag"] for s in json.load(open(args.manifest))["specimens"]}
        found = set(flags)
        missed = expected - found
        print("\n--- scored against manifest ---")
        print(f"recovered {len(found & expected)}/{len(expected)} flags")
        if missed:
            print("missed:")
            for f in sorted(missed):
                print(f"  - {f}")

    print(f"\nExecution time: {dt:.2f}s")


if __name__ == "__main__":
    main()
