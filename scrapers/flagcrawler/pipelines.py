"""Item pipelines for the flag crawler.

FlagDedupPipeline collapses the stream to distinct flags; ManifestScoringPipeline
scores those against manifest.json and prints a summary in the same shape as the
bs4 / selenium scrapers (so run_all.sh output stays consistent).
"""
import json
import time

from scrapy.exceptions import DropItem


class FlagDedupPipeline:
    """Keep the first FlagItem per flag; drop later duplicates (same flag found
    again via another surface or another page)."""

    def __init__(self):
        self.seen = set()

    def process_item(self, item, spider):
        flag = item["flag"]
        if flag in self.seen:
            raise DropItem(f"duplicate flag {flag}")
        self.seen.add(flag)
        return item


class ManifestScoringPipeline:
    """Collect distinct flags and, on close, score them against the manifest."""

    def __init__(self, manifest_path):
        self.manifest_path = manifest_path
        self.found = set()
        self.t0 = None
        self.crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        inst = cls(crawler.settings.get("MANIFEST_PATH"))
        inst.crawler = crawler
        return inst

    def open_spider(self, spider):
        self.t0 = time.time()

    def process_item(self, item, spider):
        self.found.add(item["flag"])
        return item

    def close_spider(self, spider):
        dt = time.time() - (self.t0 or time.time())
        pages = 0
        if self.crawler is not None:
            pages = self.crawler.stats.get_value("response_received_count", 0)

        print("\n" + "=" * 70)
        print(f"crawled {pages} pages in {dt:.1f}s — found {len(self.found)} distinct flag(s)")
        print("=" * 70)
        for f in sorted(self.found):
            print(f"  {f}")

        if self.manifest_path:
            with open(self.manifest_path) as fh:
                expected = {s["flag"] for s in json.load(fh)["specimens"]}
            recovered = self.found & expected
            missed = expected - self.found
            print("\n--- scored against manifest ---")
            print(f"recovered {len(recovered)}/{len(expected)} flags")
            if missed:
                print("missed:")
                for f in sorted(missed):
                    print(f"  - {f}")
            extra = self.found - expected
            if extra:
                print(f"unexpected (not in manifest): {sorted(extra)}")
