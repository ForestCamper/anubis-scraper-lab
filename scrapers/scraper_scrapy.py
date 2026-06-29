#!/usr/bin/env python3
"""
scraper_scrapy.py  —  launcher for the Scrapy + Playwright crawler.

Thin CLI wrapper that runs the `flagcrawler` Scrapy project with the same flags
as the other scrapers (--seed / --manifest / --quiet / --ocr / --max-pages), so
it slots straight into run_all.sh. Scoring is printed by the project's
ManifestScoringPipeline; this wrapper prints the overall Execution time to match
scraper_bs4.py / scraper_selenium.py.

Usage:
    python scraper_scrapy.py
    python scraper_scrapy.py --seed http://anubis:8923/index.html --manifest manifest.json
    python scraper_scrapy.py --seed http://range:8000/index.html --ocr --max-pages 6
"""
import argparse
import os
import time

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from flagcrawler.spiders.flag_spider import FlagSpider


def main():
    ap = argparse.ArgumentParser(description="Scrapy + Playwright flag crawler.")
    ap.add_argument("--seed", default=os.environ.get("SEED_URL", "http://anubis:8923/index.html"))
    ap.add_argument("--manifest", help="path to manifest.json to score coverage")
    ap.add_argument("--ocr", action="store_true", help="OCR canvas/img (needs pytesseract)")
    ap.add_argument("--isolated", action="store_true",
                    default=os.environ.get("ISOLATED", "0").lower() in ("1", "true", "yes", "on"),
                    help="give every request its own browser context so each re-solves "
                         "the Anubis PoW (simulate many distinct machines)")
    ap.add_argument("--max-pages", type=int, default=0, help="stop after N pages (0 = no limit)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    settings = get_project_settings()
    if args.manifest:
        settings.set("MANIFEST_PATH", os.path.abspath(args.manifest))
    settings.set("LOG_LEVEL", "WARNING" if args.quiet else "INFO")
    if args.max_pages:
        settings.set("CLOSESPIDER_PAGECOUNT", args.max_pages)

    print(f"scraper_scrapy: crawling from {args.seed} "
          f"(concurrency={settings.getint('CONCURRENT_REQUESTS')}, ocr={args.ocr}, "
          f"isolated={args.isolated})")

    t0 = time.time()
    process = CrawlerProcess(settings)
    process.crawl(FlagSpider, seed=args.seed, ocr="1" if args.ocr else "0",
                  isolate="1" if args.isolated else "0")
    process.start()  # blocks until the crawl finishes
    dt = time.time() - t0

    print(f"\nExecution time: {dt:.2f}s")


if __name__ == "__main__":
    main()
