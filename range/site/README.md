# The Extraction Range

A mock website that demonstrates **46 different ways websites store or embed a value**,
old and new. Every page (a "specimen") hides exactly one token of the form
`FLAG{technique-XXXXXXXX}` using one technique. If a scraper recovers the flag,
it can read data stored that way.

## Use it
- Open `index.html` directly for the ~75% of specimens that need no server.
- For storage, fetch, captions, iframes, and the HTTP-header specimen, run a server:

  ```
  cd scraper-test-range
  python3 serve.py
  # open http://localhost:8000/index.html
  ```
  `serve.py` also attaches a real `X-Access-Token` response header to the http-header page.

## Answer key
`manifest.json` lists every specimen: slug, era, category, scrape difficulty (1–5),
whether it needs a server, where the flag lives, and the flag itself — score your scraper against it.

## Specimens by difficulty
- **1–2** raw HTML/source parsing (text, tables, attributes, comments, entities, meta, marquee).
- **3** structured data + light decoding (JSON-LD, microdata, RDFa, hydration JSON, base64, data: URIs, inline JS).
- **4** JavaScript execution / browser context (rendered DOM, fetch, storage, cookies, custom elements, lazy-load, headers).
- **5** beyond the DOM (canvas pixels, shadow DOM, IndexedDB, OCR image).

Filler text on each page is random noise and never contains a flag.
