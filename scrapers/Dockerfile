FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver

# Chromium + matching driver (same apt source = no version drift), plus tesseract
# for the optional OCR specimen and fonts so rendered text rasterises correctly.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        tesseract-ocr \
        fonts-liberation \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright's own Chromium build (+ any extra system libs) for the
# scrapy-playwright crawler. Separate from the apt chromium above, which the
# selenium scraper drives via chromedriver.
RUN playwright install --with-deps chromium

COPY . /app
RUN chmod +x entrypoint.sh run_all.sh

# entrypoint waits for the range to be reachable, then runs the given command.
ENTRYPOINT ["./entrypoint.sh"]
CMD ["./run_all.sh"]
