#!/usr/bin/env bash
# Usage: publish.sh OUT_DIR SHA_FILE TAGS_FILE   (run from the repository root, i.e. the checkout of main)
# Order (ARCH 9): state (source of truth), tags, then main. Never an empty commit.
# Env: PUBLISH_REMOTE (default origin), PYTHON (default python), PUBLISH_SLEEPS (default "5 15 30"),
#      GITHUB_REPOSITORY, SOL0_NO_SIZE=1 to skip the size check.
#      GH_TOKEN (the job's GITHUB_TOKEN, passed through `env:` of the publish step only): authenticates every git
#      command of this script, as an HTTP header handed to git through GIT_CONFIG_* environment variables. The
#      checkout runs with persist-credentials: false, so no credential is stored in .git/config. The token is never
#      echoed, never put in a URL or in argv, never written to a file (no shell tracing, no git trace here); the runner masks
#      GITHUB_TOKEN by itself.
#      Server mode (LIVE-DESIGN 8.2), all optional and without effect when absent:
#      GH_TOKEN_FILE  file (0600) holding the fine-grained token; read by a git credential helper only at the moment of
#                     each git network call: the token is in no argv, no environment variable, no log (only the path is);
#      SOL0_GIT_NAME / SOL0_GIT_EMAIL  commit identity (the owner's noreply read from GET /user at install, never hardcoded);
#      PUBLISH_CFG    path of the run config used for the size limit (default config/run.toml).
set -euo pipefail
out="${1:?out dir}"
shafile="${2:?sha file}"
tagsfile="${3:-}"
remote="${PUBLISH_REMOTE:-origin}"
py="${PYTHON:-python}"
sleeps="${PUBLISH_SLEEPS:-5 15 30}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$here/publish_lib.py"
cfg="${PUBLISH_CFG:-config/run.toml}"
expected="$(cat "$shafile" 2>/dev/null || true)"
sol="$("$py" "$lib" sol "$out")"
solfmt="$(printf '%04d' "$sol")"
BOT_NAME="${SOL0_GIT_NAME:-github-actions[bot]}"
BOT_MAIL="${SOL0_GIT_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
export GIT_AUTHOR_NAME="$BOT_NAME" GIT_AUTHOR_EMAIL="$BOT_MAIL" GIT_COMMITTER_NAME="$BOT_NAME" GIT_COMMITTER_EMAIL="$BOT_MAIL"
gitid=(-c commit.gpgsign=false)

# Explicit authentication (GH_TOKEN only; absent = anonymous, e.g. tests against a local bare repository).
# Scoped to https://github.com/ so that no other host ever receives it.
if [ -n "${GH_TOKEN:-}" ]; then
  auth="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')"
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"
  export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $auth"
  unset auth
elif [ -n "${GH_TOKEN_FILE:-}" ]; then
  [ -r "$GH_TOKEN_FILE" ] || { echo "::error::token file unreadable"; exit 6; }
  # helper reads the file when git asks for a credential; only the path appears in the environment
  export SOL0_TOKEN_FILE="$GH_TOKEN_FILE"
  export GIT_TERMINAL_PROMPT=0
  export GIT_CONFIG_COUNT=2
  export GIT_CONFIG_KEY_0="credential.https://github.com.helper"
  export GIT_CONFIG_VALUE_0=""
  export GIT_CONFIG_KEY_1="credential.https://github.com.helper"
  export GIT_CONFIG_VALUE_1='!f() { echo username=x-access-token; printf "password=%s\n" "$(cat "$SOL0_TOKEN_FILE")"; }; f'
fi

# A refusal caused by a branch protection or a ruleset (GH006 / GH013) is not a race: retrying cannot help.
protected_refusal() {  # protected_refusal FILE -> 0 when the git output shows a protection/ruleset refusal
  grep -qE 'GH006|GH013|protected branch|Repository rule violations' "$1"
}

orphan_commit() {  # orphan_commit DIR MESSAGE -> prints commit sha, working copy and real index untouched
  local d="$1" msg="$2" idx tree
  idx="$(mktemp -u "${TMPDIR:-/tmp}/idx.XXXXXX")"
  GIT_INDEX_FILE="$idx" git --work-tree="$d" add -A -f -- .
  tree="$(GIT_INDEX_FILE="$idx" git write-tree)"
  rm -f "$idx"
  git "${gitid[@]}" commit-tree -m "$msg" "$tree" </dev/null
}

remote_sha() {  # remote_sha REF -> sha or empty ; returns 1 when the remote is unreachable
  local o
  o="$(git ls-remote "$remote" "$1")" || return 1
  printf '%s' "${o%%[[:space:]]*}"
}

# (1)(2) state
commit="$(orphan_commit "$out" "sol $solfmt")"
echo "state commit: $commit (expected remote: [$expected])"
pushed=0
attempt=0
for s in 0 $sleeps; do
  [ "$s" != 0 ] && { echo "::warning::state push retry in ${s}s"; sleep "$s"; }
  attempt=$((attempt + 1))
  perr="$(mktemp "${TMPDIR:-/tmp}/perr.XXXXXX")"
  prc=0
  git push --force-with-lease="refs/heads/state:$expected" "$remote" "$commit:refs/heads/state" 2>"$perr" || prc=$?
  cat "$perr" >&2
  if [ "$prc" -eq 0 ]; then rm -f "$perr"; pushed=1; break; fi
  if protected_refusal "$perr"; then
    rm -f "$perr"
    echo "::error::state push refused by a branch protection or ruleset on state (no force push allowed?); see docs/milestones/J9f.md; nothing else pushed"
    exit 6
  fi
  rm -f "$perr"
  if now="$(remote_sha refs/heads/state)"; then
    if [ "$now" = "$commit" ]; then
      echo "lease refused but remote == local commit: success (lost answer)"; pushed=1; break
    elif [ "$now" != "$expected" ]; then
      echo "::error::state changed on the remote (lease refused): remote=[$now] expected=[$expected]; nothing else pushed"
      exit 5
    fi
    # remote unchanged: transient error, retry
  fi
done
if [ "$pushed" != 1 ]; then
  echo "::error::state push failed after $attempt attempts"
  exit 4
fi
echo "state pushed: $commit"
# Server contract (publisher.py: « publish.sh writes the pushed commit here »): the next run's lease expects it.
# Without it every publication after the first is refused (lease on an empty expected value). Actions mode: harmless.
{ printf '%s\n' "$commit" > "$shafile.tmp.$$" && mv -f "$shafile.tmp.$$" "$shafile"; } 2>/dev/null \
  || echo "::warning::could not record the pushed state commit in $shafile"

# (3) tags
if [ -n "$tagsfile" ] && [ -s "$tagsfile" ]; then
  while read -r tag dir _rest; do
    [ -z "${tag:-}" ] && continue
    if ! [[ "$tag" =~ ^[A-Za-z0-9._-]+$ ]]; then echo "::warning::tag name refused: $tag"; continue; fi
    if t="$(remote_sha "refs/tags/$tag")" && [ -n "$t" ]; then echo "tag $tag already present"; continue; fi
    (
      set -e
      snap="$(mktemp -d "${TMPDIR:-/tmp}/snap.XXXXXX")"
      trap 'rm -rf "$snap"' EXIT
      for f in console.gif status.svg map.png; do
        [ -f "$dir/$f" ] && cp "$dir/$f" "$snap/$f"
      done
      "$py" "$lib" milestone "$tag" "$out" > "$snap/milestone.json"
      c="$(orphan_commit "$snap" "milestone $tag")"
      git tag -f "$tag" "$c" >/dev/null
      git push "$remote" "refs/tags/$tag:refs/tags/$tag"
    ) && echo "tag $tag pushed" || echo "::warning::tag $tag not pushed (stays in pending_tags, retried next run)"
  done < "$tagsfile"
fi

# (4) main: journal, atlas, firsts (append only)
main_ok=1
for d in journal atlas firsts; do [ -e "$d" ] && git add -A -- "$d"; done || true
if git diff --cached --quiet; then
  echo "nothing to commit on main"
else
  git "${gitid[@]}" commit -q -m "journal: sol $solfmt"
  main_ok=0
  attempt=0
  while [ "$attempt" -lt 3 ]; do
    attempt=$((attempt + 1))
    perr="$(mktemp "${TMPDIR:-/tmp}/perr.XXXXXX")"
    prc=0
    git push "$remote" HEAD:main 2>"$perr" || prc=$?
    cat "$perr" >&2
    if [ "$prc" -eq 0 ]; then rm -f "$perr"; main_ok=1; break; fi
    if protected_refusal "$perr"; then
      rm -f "$perr"
      echo "::warning::main push refused by a branch protection or ruleset: no retry (add the GitHub Actions app to the bypass list, or remove the rule)"
      break
    fi
    rm -f "$perr"
    echo "::warning::main push refused (attempt $attempt), rebasing"
    if ! { git fetch "$remote" main && git "${gitid[@]}" rebase "$remote/main"; }; then
      git rebase --abort 2>/dev/null || true
      echo "::warning::rebase conflict: journal commit abandoned, the entry stays in journal_tail"
      break
    fi
  done
  [ "$main_ok" = 1 ] || echo "::warning::main not updated"
fi

# (5) repository size (informative)
if [ "${SOL0_NO_SIZE:-0}" != 1 ] && [ -n "${GITHUB_REPOSITORY:-}" ] && command -v gh >/dev/null 2>&1; then
  if size="$(gh api "repos/$GITHUB_REPOSITORY" -q .size 2>/dev/null)"; then
    limit="$("$py" "$lib" sizelimit "$cfg")"
    if [ "$size" -gt "$limit" ]; then echo "::warning::repository size $size KB > $limit KB"; else echo "::notice::repository size $size KB"; fi
  else
    echo "::notice::repository size unavailable"
  fi
fi

# (6) exit code
"$py" "$lib" verdict "$out" "$cfg" "$main_ok"
