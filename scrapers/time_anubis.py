#!/usr/bin/env python3
"""
time_anubis.py  —  reference timing probe.

Opens *one* page (the seed) in a real headless Chrome and measures how long it
takes to get through Anubis. Because it is a real browser, it runs the Anubis
proof-of-work challenge JS, gets the clearance cookie, and is redirected to the
actual page — exactly like scraper_selenium.py does, but without any crawling or
flag harvesting. Its only job is to report the wall-clock time of the Anubis
trial + first page load.

"Challenge solved" is detected by waiting for the real page to render: the
range's index has the title "The Extraction Range — …", which the Anubis
interstitial does not. Override the marker with --expect-title if you point it
at a different page.

Usage:
    python3 time_anubis.py
    python3 time_anubis.py --seed http://anubis:8923/index.html
    python3 time_anubis.py --expect-title "Extraction Range" --timeout 60
"""
import argparse
import os
import time

from selenium.webdriver.support.ui import WebDriverWait

# Reuse the exact same driver setup as the real scraper so the timing is
# representative (same Chrome flags, same env-based binary/grid detection).
from scraper_selenium import make_driver


def main():
    ap = argparse.ArgumentParser(description="Time how long Anubis takes to let one page through.")
    ap.add_argument("--seed", default=os.environ.get("SEED_URL", "http://anubis:8923/index.html"))
    ap.add_argument("--expect-title", default="Extraction Range",
                    help="substring that appears in the real page title once the "
                         "Anubis challenge is solved (default: 'Extraction Range')")
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="max seconds to wait for the challenge to clear")
    ap.add_argument("--headful", action="store_true")
    args = ap.parse_args()

    print(f"time_anubis: opening {args.seed} (expecting title to contain "
          f"'{args.expect_title}') ...")

    driver = make_driver(headful=args.headful)
    try:
        t0 = time.time()
        driver.get(args.seed)
        # Wait until the real page renders — i.e. Anubis has been solved and we
        # were redirected past the interstitial to the actual content.
        WebDriverWait(driver, args.timeout).until(
            lambda d: args.expect_title.lower() in (d.title or "").lower())
        dt = time.time() - t0
        title = driver.title
    except Exception as e:
        dt = time.time() - t0
        last_title = (driver.title or "").strip()
        print(f"time_anubis: did NOT reach the page in {args.timeout:.0f}s "
              f"({e.__class__.__name__}). Current title: {last_title!r}")
        print(f"Execution time: {dt:.2f}s (TIMED OUT)")
        raise SystemExit(1)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print(f"time_anubis: reached '{title}' — Anubis challenge cleared.")
    print(f"Execution time: {dt:.2f}s")


if __name__ == "__main__":
    main()
