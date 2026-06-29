FROM python:3.12-slim

# The range is pure stdlib (serve.py + static files) — no extra deps needed.
WORKDIR /site
COPY site/ /site/

EXPOSE 8000

# serve.py binds 0.0.0.0:8000, serves this directory, and attaches the
# X-Access-Token header to the http-header specimen.
HEALTHCHECK --interval=3s --timeout=3s --retries=20 --start-period=2s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/index.html').read()" || exit 1

CMD ["python", "serve.py"]
