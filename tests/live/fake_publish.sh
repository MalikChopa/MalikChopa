#!/bin/bash
# Fake publish.sh for tests: records its arguments, writes a fake commit id. No git, no network, no token.
set -eu
out="$1"; shafile="$2"; tags="$3"
log="$(dirname "$shafile")/publish-calls.log"
printf 'out=%s tags=%s\n' "$(basename "$out")" "$(wc -l < "$tags" | tr -d ' ')" >> "$log"
printf 'fakecommit%s\n' "$(basename "$out" | tr -d '-')" > "$shafile"
exit "${FAKE_PUBLISH_CODE:-0}"
