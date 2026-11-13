#!/usr/bin/env bash
# Undo one install.sh run: rollback.sh <UTC-stamp> [--root DIR]. Replays undo.log backwards.
# Files created are removed, files changed are restored, links and directories likewise.
# Packages, users, firewall and service state are NOT reverted (logged as "note").
set -euo pipefail
STAMP="${1:-}"; ROOT=""
[ $# -ge 1 ] || { echo "usage: rollback.sh <UTC-stamp> [--root DIR]" >&2; exit 2; }
shift
while [ $# -gt 0 ]; do
  case "$1" in --root) ROOT="${2:?}"; shift ;; *) echo "unknown option: $1" >&2; exit 2 ;; esac
  shift
done
ROOT="${ROOT%/}"
[[ "$STAMP" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || { echo "bad stamp" >&2; exit 2; }
BK="$ROOT/var/backups/sol0/$STAMP"
LOG="$BK/undo.log"
[ -f "$LOG" ] || { echo "no undo.log for $STAMP" >&2; exit 1; }
n=0
# reverse order (tail -r on macOS, tac on Linux)
if command -v tac >/dev/null 2>&1; then REV=(tac); else REV=(tail -r); fi
while IFS=$'\t' read -r verb a b; do
  case "$verb" in
    remove) rm -f "$a" ;;
    restore) cp -p "$b" "$a" ;;
    relink) ln -sfn "$b" "$a" ;;
    rmdir) rmdir "$a" 2>/dev/null || echo "  keep $a (not empty)" ;;
    note) echo "  note: $a" ;;
    *) echo "unknown verb $verb" >&2; exit 1 ;;
  esac
  n=$((n + 1))
done < <("${REV[@]}" "$LOG")
echo "rollback $STAMP: $n undo step(s)"
