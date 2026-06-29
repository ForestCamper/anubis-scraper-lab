#!/usr/bin/env bash
set -e

SEED_URL="${SEED_URL:-http://range:8000/index.html}"
OCR_FLAG=""
[ "${OCR:-0}" = "1" ] && OCR_FLAG="--ocr"

echo
echo "############################################################"
echo "#  0) Reference: time the Anubis challenge (single page)"
echo "############################################################"
python time_anubis.py --seed "$SEED_URL" || echo "(timing probe failed — continuing)"

echo
echo "############################################################"
echo "#  1) BeautifulSoup crawler (raw HTML only)"
echo "############################################################"
python scraper_bs4.py --seed "$SEED_URL" --manifest manifest.json --quiet

echo
echo "############################################################"
echo "#  2) Selenium crawler (headless Chromium)  OCR=${OCR:-0}"
echo "############################################################"
python scraper_selenium.py --seed "$SEED_URL" --manifest manifest.json --quiet $OCR_FLAG

echo
echo "############################################################"
echo "#  3) Scrapy + Playwright crawler (full project)  OCR=${OCR:-0}"
echo "############################################################"
python scraper_scrapy.py --seed "$SEED_URL" --manifest manifest.json --quiet $OCR_FLAG --isolated

echo
echo "done. (set OCR=1 to also crack the image specimen)"
