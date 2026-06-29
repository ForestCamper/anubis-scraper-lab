#!/usr/bin/env bash
set -e

SEED_URL="${SEED_URL:-http://range:8000/index.html}"
export SEED_URL

echo "scrapers: waiting for the range at ${SEED_URL} ..."
python - <<'PY'
import os, sys, time, urllib.request, urllib.error
seed = os.environ["SEED_URL"]
for i in range(120):
    try:
        urllib.request.urlopen(seed, timeout=2).read()
        print("scrapers: range is up.")
        sys.exit(0)
    except urllib.error.HTTPError:
        # Any HTTP response (including Anubis challenge pages: 401/403) means
        # the server is reachable — treat it as "up".
        print("scrapers: range is up (got HTTP challenge response).")
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("scrapers: range never came up — giving up.", file=sys.stderr)
sys.exit(1)
PY

exec "$@"
