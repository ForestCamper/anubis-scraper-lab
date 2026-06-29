"""Downloader middleware for the flag crawler.

AnubisAwareMiddleware is intentionally light: it just observes whether Anubis
served its proof-of-work interstitial for a response. Because the spider waits
(via Playwright) for the challenge to clear before the response is handed back,
a cleared response no longer contains the '#anubis_challenge' marker — so a hit
here means a page that was *not* solved in time. Useful signal when tuning
difficulty / timeouts, and a small demonstration of Scrapy's middleware layer.
"""


class AnubisAwareMiddleware:
    def __init__(self):
        self.challenged = 0

    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_response(self, request, response, spider):
        try:
            body = response.text
        except Exception:
            return response
        if 'id="anubis_challenge"' in body:
            self.challenged += 1
            spider.logger.warning(
                "Anubis interstitial still present for %s "
                "(PoW not solved within the wait window)", response.url)
        return response
