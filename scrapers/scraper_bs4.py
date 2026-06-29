#!/usr/bin/env python3
"""
scraper_bs4.py  —  the simple crawler.

Recursively walks a site by following the <a href> links it finds, remembers
which URLs it has already visited (so it never fetches one twice), and scans the
RAW HTML of every response for FLAG{...} tokens.

This is deliberately naive: it only sees what is literally present in the HTML
bytes the server sends. It therefore finds every flag that sits in the source —
text nodes, attributes, comments, inline <script>/<style>, JSON-LD, meta tags —
but is blind to anything that is encoded, rendered by JavaScript, stored in the
browser, loaded as a separate resource, or embedded only via <iframe>/<track>/<img>.
That blindness is the whole point: compare its result with scraper_selenium.py.

Usage:
    python3 scraper_bs4.py
    python3 scraper_bs4.py --seed http://localhost:8000/index.html
    python3 scraper_bs4.py --manifest ../scraper-test-range/manifest.json   # score it
"""
import argparse
import os
import re
import sys
import time
from collections import deque
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from bs4 import BeautifulSoup

FLAG_RE = re.compile(r"FLAG\{[A-Za-z0-9_-]+\}")  # real flags only; ignores FLAG{…} prose
# extensions we will not even fetch (binary / non-HTML)
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css", ".js",
            ".json", ".vtt", ".pdf", ".zip", ".svg", ".woff", ".woff2", ".ttf")


def in_scope(url, root):
    """Same host (and port) as the seed — never wander off onto the live web."""
    u, r = urlparse(url), urlparse(root)
    return u.scheme in ("http", "https") and u.netloc == r.netloc


def crawl(seed, delay=0.0, max_pages=10_000, timeout=10, verbose=True):
    seen = set()                 # URLs we have already queued/visited
    queue = deque([seed])
    seen.add(seed)
    flags = {}                   # flag -> set(urls where it was seen)
    pages_visited = 0
    session = requests.Session()
    session.headers["User-Agent"] = "extraction-range-bs4/1.0"

    while queue and pages_visited < max_pages:
        url = queue.popleft()
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as e:
            if verbose:
                print(f"  ! skip {url}  ({e.__class__.__name__})")
            continue
        pages_visited += 1

        ctype = resp.headers.get("Content-Type", "")
        # We crawl HTML; anything non-HTML we still text-scan but don't parse links.
        html = resp.text

        # 1) hunt for flags in the raw response text
        hits = set(FLAG_RE.findall(html))
        for f in hits:
            flags.setdefault(f, set()).add(url)
        flag_note = f"  <-- {len(hits)} flag(s)" if hits else ""
        if verbose:
            print(f"[{pages_visited:>3}] {url}{flag_note}")

        # 2) follow <a href> links if this looks like HTML
        if "html" in ctype or html.lstrip().lower().startswith(("<!doctype", "<html")):
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                nxt, _ = urldefrag(urljoin(url, a["href"]))   # resolve + drop #fragment
                if not in_scope(nxt, seed):
                    continue
                if nxt.lower().endswith(SKIP_EXT):
                    continue
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

        if delay:
            time.sleep(delay)

    return flags, pages_visited


def main():
    ap = argparse.ArgumentParser(description="Simple BeautifulSoup flag crawler.")
    ap.add_argument("--seed", default=os.environ.get("SEED_URL", "http://localhost:8000/index.html"),
                    help="URL to start from (default: $SEED_URL or the local Extraction Range)")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between requests")
    ap.add_argument("--max-pages", type=int, default=10_000)
    ap.add_argument("--manifest", help="path to manifest.json to score coverage")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    flags, n = crawl(args.seed, delay=args.delay, max_pages=args.max_pages,
                     verbose=not args.quiet)
    dt = time.time() - t0

    print("\n" + "=" * 64)
    print(f"crawled {n} pages in {dt:.2f}s — found {len(flags)} distinct flag(s)")
    print("=" * 64)
    for f in sorted(flags):
        print(f"  {f}")

    if args.manifest:
        import json
        expected = {s["flag"] for s in json.load(open(args.manifest))["specimens"]}
        found = set(flags)
        missed = expected - found
        print("\n--- scored against manifest ---")
        print(f"recovered {len(found & expected)}/{len(expected)} flags")
        if missed:
            print(f"missed {len(missed)} (these need decoding, JS, storage, or "
                  f"non-anchor resources):")
            for f in sorted(missed):
                print(f"  - {f}")
        extra = found - expected
        if extra:
            print(f"unexpected (not in manifest): {sorted(extra)}")

    print(f"\nExecution time: {dt:.2f}s")


if __name__ == "__main__":
    main()
