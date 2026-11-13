#!/usr/bin/env bash
# Health check: exit 0 if /health answers 200. Usage: healthcheck.sh [URL] (default local).
set -u
url="${1:-http://127.0.0.1:4180/health}"
code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url" || true)
echo "health $url -> ${code:-none}"
[ "$code" = "200" ]
