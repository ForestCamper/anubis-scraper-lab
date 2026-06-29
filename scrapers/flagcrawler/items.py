"""Items produced by the flag crawler.

A FlagItem is one FLAG{...} token recovered from one surface of one page. The
ManifestScoringPipeline scores the distinct flags against manifest.json; the
JSON feed (see settings.FEEDS) keeps the full per-flag provenance.
"""
import scrapy


class FlagItem(scrapy.Item):
    flag = scrapy.Field()          # the FLAG{...} token
    source_url = scrapy.Field()    # page it was recovered from
    page_title = scrapy.Field()    # <title> of that page (when available)
    technique = scrapy.Field()     # which surface surfaced it (e.g. "localStorage")
    http_status = scrapy.Field()   # response status for the page
