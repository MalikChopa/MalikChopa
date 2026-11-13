#!/usr/bin/env bash
# Sol-0 live server kit. Target: Ubuntu 24.04 LTS x86-64 (any VPS; deployed on Contabo). Run as root.
# Idempotent: every step plans, then applies. --dry-run lists and touches nothing.
# --root DIR works on a copy of the tree (tests on the Mac): system actions are simulated.
# Never reads, prints or stores a token: see `sol0ctl token set`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE"
ROOT=""; DRY=0; DOMAIN=""; PAGES_ORIGIN=""; REPO=""; SHA=""; SRC=""; PAGE_SHA=""; SITE_APEX=""; CANONICAL=""; OPS_KEY=""
usage() { echo "usage: install.sh [--dry-run] [--root DIR] --domain D --pages-origin URL --repo OWNER/NAME --sha COMMIT [--page-sha COMMIT] [--site-apex on|off] [--canonical off|apex] [--src GIT_URL_OR_DIR] [--ops-key PUBKEY_FILE]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --root) ROOT="${2:?}"; shift ;;
    --domain) DOMAIN="${2:?}"; shift ;;
    --pages-origin) PAGES_ORIGIN="${2:?}"; shift ;;
    --repo) REPO="${2:?}"; shift ;;
    --sha) SHA="${2:?}"; shift ;;
    --src) SRC="${2:?}"; shift ;;
    --page-sha) PAGE_SHA="${2:?}"; shift ;;
    --site-apex) SITE_APEX="${2:?}"; shift ;;
    --canonical) CANONICAL="${2:?}"; shift ;;
    --ops-key) OPS_KEY="${2:?}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
ROOT="${ROOT%/}"
[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$ ]] || { echo "bad or missing --domain" >&2; exit 2; }
[[ "$PAGES_ORIGIN" =~ ^https://[A-Za-z0-9.-]+$ ]] || { echo "bad or missing --pages-origin (https://host, no path)" >&2; exit 2; }
[[ "$REPO" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "bad or missing --repo" >&2; exit 2; }
[[ "$SHA" =~ ^[0-9a-f]{7,40}$ ]] || { echo "bad or missing --sha (hex commit)" >&2; exit 2; }
[ -z "$PAGE_SHA" ] && PAGE_SHA="$SHA"
[[ "$PAGE_SHA" =~ ^[0-9a-f]{7,40}$ ]] || { echo "bad --page-sha (hex commit)" >&2; exit 2; }
[ -z "$SRC" ] && SRC="https://github.com/$REPO.git"
[ -n "$ROOT" ] && { [ -d "$ROOT" ] || { echo "--root: not a directory" >&2; exit 2; }; }
# --ops-key: the PUBLIC key of the read-only operator account sol0ops (SEC-03). One line, modern key types only, a plain
# comment; never a private key. Checked here, before any change.
OPS_KEY_LINE=""
if [ -n "$OPS_KEY" ]; then
  [ -f "$OPS_KEY" ] || { echo "--ops-key: file not found" >&2; exit 2; }
  grep -q 'PRIVATE KEY' "$OPS_KEY" && { echo "--ops-key: this is a PRIVATE key; give the .pub file. Nothing changed." >&2; exit 2; }
  [ "$(grep -c . "$OPS_KEY")" = 1 ] || { echo "--ops-key: exactly one key line expected" >&2; exit 2; }
  OPS_KEY_LINE="$(grep . "$OPS_KEY")"
  [[ "$OPS_KEY_LINE" =~ ^(ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)\ [A-Za-z0-9+/]{40,}={0,3}(\ [A-Za-z0-9@._+-]{1,64})?$ ]] \
    || { echo "--ops-key: not a public key line (ssh-ed25519 or ecdsa, base64, optional plain comment). Nothing changed." >&2; exit 2; }
fi
[ -z "$ROOT" ] && [ "$(id -u)" != 0 ] && [ "$DRY" = 0 ] && { echo "run as root (or use --dry-run / --root)" >&2; exit 2; }

# shellcheck source=lib/plan.sh
. "$HERE/lib/plan.sh"
STAMP="${SOL0_NOW:-$(date -u +%Y%m%dT%H%M%SZ)}"
ck() { if [ -f "$1" ]; then cksum < "$1" | cut -d" " -f1; else echo none; fi; }   # checksum of a file, "none" if absent
TMPD="$(mktemp -d)"; trap 'rm -rf "$TMPD"' EXIT

# ---- site flags (sol0.fr). Given on the command line, they are remembered in /etc/sol0/site.flags (a re-run without flags keeps them).
FLAGS_FILE="$(p /etc/sol0/site.flags)"
FLAGS_EXPLICIT=0
[ -n "$SITE_APEX$CANONICAL" ] && FLAGS_EXPLICIT=1
if [ -f "$FLAGS_FILE" ]; then
  [ -z "$SITE_APEX" ] && SITE_APEX="$(sed -n 's/^site_apex=//p' "$FLAGS_FILE" | head -n1)"
  [ -z "$CANONICAL" ] && CANONICAL="$(sed -n 's/^canonical=//p' "$FLAGS_FILE" | head -n1)"
fi
SITE_APEX="${SITE_APEX:-off}"; CANONICAL="${CANONICAL:-off}"
[[ "$SITE_APEX" =~ ^(on|off)$ ]] || { echo "bad --site-apex (on|off)" >&2; exit 2; }
[[ "$CANONICAL" =~ ^(off|apex)$ ]] || { echo "bad --canonical (off|apex)" >&2; exit 2; }
[ "$CANONICAL" = apex ] && [ "$SITE_APEX" != on ] && { echo "--canonical apex needs --site-apex on" >&2; exit 2; }

# DNS guard: sol0.fr and www must already point to THIS server (same addresses as live.), else Caddy would loop on ACME
# and could exhaust the certificate authority limits. Refuses before any change. SOL0_DNS_FILE (tests): lines "A|AAAA name address".
dns_list() { # dns_list A|AAAA name
  if [ -n "${SOL0_DNS_FILE:-}" ]; then awk -v t="$1" -v n="$2" '$1==t && $2==n {print $3}' "$SOL0_DNS_FILE" | sort -u
  elif [ "$1" = A ]; then { getent ahostsv4 "$2" 2>/dev/null || true; } | awk '{print $1}' | sort -u
  else { getent ahostsv6 "$2" 2>/dev/null || true; } | awk 'tolower($1) !~ /^::ffff:/ {print $1}' | sort -u; fi   # glibc maps A records into ahostsv6 (::ffff:a.b.c.d): not an AAAA
}
if [ "$SITE_APEX" = on ]; then
  live4="$(dns_list A "live.$DOMAIN")"; live6="$(dns_list AAAA "live.$DOMAIN")"
  [ -n "$live4$live6" ] || { echo "DNS guard: live.$DOMAIN does not resolve: cannot tell where this server is. Nothing changed." >&2; exit 1; }
  for h in "$DOMAIN" "www.$DOMAIN"; do
    if [ "$(dns_list A "$h")" != "$live4" ] || { [ -n "$(dns_list AAAA "$h")" ] && [ "$(dns_list AAAA "$h")" != "$live6" ]; }; then
      echo "DNS guard: $h does not point to this server (A $(dns_list A "$h" | tr '\n' ' ') / AAAA $(dns_list AAAA "$h" | tr '\n' ' ') ; expected A ${live4:-none})." >&2
      echo "Fix the records at the registrar, check with: dig +short A $h ; dig +short AAAA $h ; then run again. Nothing changed." >&2
      exit 1
    fi
  done
fi

[ "$DRY" = 0 ] && bk_init
say "Sol-0 install ($([ "$DRY" = 1 ] && echo dry-run || echo apply)) root='${ROOT:-/}' domain=live.$DOMAIN sha=$SHA page-sha=$PAGE_SHA site-apex=$SITE_APEX canonical=$CANONICAL"

# ---- S1 checks
say "S1 checks"
if [ -n "$ROOT" ]; then
  say "  (skipped under --root: OS, disk, NTP, SSH key)"
else
  . /etc/os-release
  [ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = "24.04" ] || { echo "S1: Ubuntu 24.04 required" >&2; exit 1; }
  [ "$(uname -m)" = x86_64 ] || { echo "S1: x86-64 required" >&2; exit 1; }
  free_kb="$(df -Pk / | awk 'NR==2{print $4}')"
  [ "$free_kb" -ge 10485760 ] || { echo "S1: 10 GB free required" >&2; exit 1; }
  timedatectl show -p NTPSynchronized --value 2>/dev/null | grep -q yes || say "  WARN  NTP not synchronised yet (S2 enables systemd-timesyncd; the engine refuses to start until it is: see ntp_check.sh)"
  [ -s /root/.ssh/authorized_keys ] || say "  WARN  no SSH key in /root/.ssh/authorized_keys: S9 will be skipped"
fi

# ---- S2 packages
say "S2 packages"
PKGS="python3.12-venv git caddy ufw unattended-upgrades curl systemd-timesyncd"
pk_check() { for x in $PKGS; do dpkg -s "$x" >/dev/null 2>&1 || return 1; done; }
pk_apply() { DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y $PKGS; }
act pkgs "apt-get install $PKGS" pk_check pk_apply
ntp_check() { timedatectl show -p NTP --value 2>/dev/null | grep -q yes; }
ntp_apply() { systemctl enable --now systemd-timesyncd && timedatectl set-ntp true; }
act time-sync "enable systemd-timesyncd and NTP (the engine refuses to start when the clock is not synchronised)" ntp_check ntp_apply

# ---- S3 users and directories
say "S3 users, directories"
us_check() { id sol0 >/dev/null 2>&1 && id sol0web >/dev/null 2>&1 && getent group sol0stream >/dev/null; }
us_apply() {
  getent group sol0stream >/dev/null || groupadd --system sol0stream
  id sol0 >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/sol0 --shell /usr/sbin/nologin -G sol0stream sol0
  id sol0web >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin -g sol0stream sol0web
}
act users "users sol0 (engine), sol0web (group sol0stream), group sol0stream" us_check us_apply
ensure_dir /var/lib/sol0 0750 sol0:sol0
ensure_dir /var/lib/sol0/secret 0700 sol0:sol0
ensure_dir /var/lib/sol0/outs 0750 sol0:sol0
ensure_dir /var/lib/sol0/live 0750 sol0:sol0
ensure_dir /var/lib/sol0-stream 2750 sol0:sol0stream   # setgid: engine files inherit group sol0stream (readable by sol0web)
ensure_dir /var/log/sol0 0750 root:adm
ensure_dir /etc/sol0 0755 root:root
ensure_dir /opt/sol0 0755 root:root
ensure_dir /opt/sol0/releases 0755 root:root
ensure_dir /opt/sol0/page-releases 0755 root:root

# ---- S4 release, venv
say "S4 release $SHA, venv, refs"
REL="/opt/sol0/releases/$SHA"
rel_check() { [ -x "$REL/venv/bin/python" ] && [ -f "$REL/.refs-done" ]; }
rel_apply() {
  [ -d "$REL/.git" ] || { rm -rf "$REL"; git clone --quiet "$SRC" "$REL"; }
  git -C "$REL" checkout --quiet --detach "$SHA"
  python3.12 -m venv "$REL/venv"
  "$REL/venv/bin/pip" install --quiet --no-deps --only-binary=:all: --require-hashes -r "$REL/requirements.lock"
  ( cd "$REL" && PYTHONPATH=src HOME=/var/lib/sol0 "$REL/venv/bin/python" -m rover refs --out "$REL/refs.json" ) && : > "$REL/.refs-done"
  chown -R root:root "$REL"; chmod -R go-w "$REL"
}
act "release-$SHA" "clone $SRC at $SHA into $REL, venv from requirements.lock (--require-hashes), rover refs" rel_check rel_apply
ensure_link /opt/sol0/app "releases/$SHA"
ensure_link /opt/sol0/venv "releases/$SHA/venv"

# ---- S4b page (built from the deployed commit, never hand-copied). Separate from S4 on purpose: a page-only deploy
# (--page-sha) must never touch the engine release, its venv or the /opt/sol0/app and /opt/sol0/venv links.
say "S4b page $PAGE_SHA (https://live.$DOMAIN/)"
PAGE_REL="/opt/sol0/page-releases/$PAGE_SHA"
PY_BUILD="${SOL0_PY:-python3.12}"
# SEO plan, lot A: with sol0.fr on, the page is built with --site https://<domain> (head, robots.txt, sitemap.xml) when
# that commit's build_page.py knows the option. The requested value is kept next to the build (<sha>.opts, outside the
# served folder): a change of the flag rebuilds the page, a re-run does not. No .opts (older kit) = built without --site.
SITE_URL=""; [ "$SITE_APEX" = on ] && SITE_URL="https://$DOMAIN"
[ -n "$ROOT" ] && ! command -v "$PY_BUILD" >/dev/null 2>&1 && PY_BUILD=python3   # tests on a machine without python3.12
page_check() {
  local d; d="$(p "$PAGE_REL")"
  [ -f "$d/index.html" ] && [ -f "$d/.sol0-page" ] && grep -q "\"stream\":\"https://live.$DOMAIN\"" "$d/config.json" 2>/dev/null \
    && [ "$(cat "$d.opts" 2>/dev/null || echo site=)" = "site=$SITE_URL" ]
}
page_apply() {
  local src full new
  full="$(p "$PAGE_REL")"; new="$full.new.$$"
  if [ -n "$ROOT" ] && [ -n "${SOL0_PAGE_SRC:-}" ]; then src="$SOL0_PAGE_SRC"                # tests only: another tree
  elif [ -n "$ROOT" ] && [ -z "${SOL0_PAGE_GIT:-}" ]; then src="$(cd "$KIT/../.." && pwd)"   # tests: the kit's own tree stands for the commit
  # SOL0_PAGE_GIT=1 (tests only): under --root, take the real git path (clone --src, checkout --page-sha)
  elif [ "$PAGE_SHA" = "$SHA" ] && [ -d "$REL/.git" ]; then src="$REL"
  else src="$TMPD/page-src"; git clone --quiet "$SRC" "$src"; git -C "$src" checkout --quiet --detach "$PAGE_SHA"; fi
  rm -rf "$new"
  # « en vie depuis » : the birth time is the dated fact of the server's own birth record (never guessed, never typed);
  # passed only when that page's build_page.py knows --birth-utc and the rover is born.
  local birth=() bu=""
  if grep -q -- '--birth-utc' "$src/tools/live/build_page.py" 2>/dev/null && [ -f "$(p /var/lib/sol0/live/birth.json)" ]; then
    bu="$("$PY_BUILD" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["birth_utc"])' "$(p /var/lib/sol0/live/birth.json)" 2>/dev/null || true)"
    [ -n "$bu" ] && birth=(--birth-utc "$bu")
  fi
  local site=()
  if [ -n "$SITE_URL" ] && grep -Eq -- "[\"']--site[\"']" "$src/tools/live/build_page.py" 2>/dev/null; then site=(--site "$SITE_URL"); fi
  "$PY_BUILD" -I "$src/tools/live/build_page.py" --repo "$REPO" --stream "https://live.$DOMAIN" ${birth[@]+"${birth[@]}"} ${site[@]+"${site[@]}"} --src "$src/pages/live" --out "$new" >/dev/null
  chmod -R go-w "$new"; chmod -R a+rX "$new"
  [ -z "$ROOT" ] && chown -R root:root "$new"
  if [ -e "$full" ] || [ -L "$full" ]; then
    # Rebuilt in place (other options, a build by an older kit without .opts, a damaged build): the previous build is
    # set aside as <sha>.prev.<UTC>, never removed, and rollback.sh puts it back (verb untree). Audit VERIF-S I1: a plain
    # rm here left /opt/sol0/page dangling after a rollback. The undo line is written between the two moves: a cut there
    # still rolls back to the previous build.
    local prev="$full.prev.$STAMP" i=0
    while [ -e "$prev" ] || [ -L "$prev" ]; do i=$((i + 1)); prev="$full.prev.$STAMP.$i"; done
    mv "$full" "$prev"
    undo "$(printf 'untree\t%s\t%s' "$full" "$prev")"
    mv "$new" "$full"
    say "  NOTE  previous build kept as ${prev#"$ROOT"} (put back by rollback.sh $STAMP; remove it by hand once the page is checked)"
  else
    mv "$new" "$full"
    undo "$(printf 'rmtree\t%s' "$full")"
  fi
  [ -e "$full.opts" ] && undo "$(printf 'restore\t%s\t%s' "$full.opts" "$(bk_copy "$full.opts")")" || undo "$(printf 'remove\t%s' "$full.opts")"
  printf 'site=%s\n' "$SITE_URL" > "$full.opts"; chmod 0644 "$full.opts"
}
if ! page_check; then
  page_prev=""; { [ -e "$(p "$PAGE_REL")" ] || [ -L "$(p "$PAGE_REL")" ]; } && page_prev="; rebuilt in place, the previous build is kept as $PAGE_SHA.prev.<UTC> and put back by rollback.sh"
  plan_note "build the page at $PAGE_SHA into $PAGE_REL (build_page.py --stream https://live.$DOMAIN${SITE_URL:+ --site $SITE_URL if known}, stdlib only, no network$page_prev)"
  if [ "$DRY" = 0 ]; then bk_init; page_apply; fi
fi
ensure_link /opt/sol0/page "page-releases/$PAGE_SHA"

# ---- S5 config (created once, never overwritten: the owner edits publish/token_expires later)
say "S5 /etc/sol0/live.toml"
cat > "$TMPD/live.toml" <<TOML
# Sol-0 live settings (this file is kept by install.sh once created)
repo = "$REPO"
publish = "off"
pages_origin = "$PAGES_ORIGIN"
data_dir = "/var/lib/sol0"
token_file = "/var/lib/sol0/secret/github-token"
identity_file = "/var/lib/sol0/secret/identity"
token_expires = ""
TOML
if [ ! -e "$(p /etc/sol0/live.toml)" ]; then ensure_file /etc/sol0/live.toml 0644 root:root "$TMPD/live.toml"; fi

# ---- S5b publication clone (SEC-01). publish.sh runs inside /var/lib/sol0/repo: it must be a git clone of the profile
# repository, made by sol0, with an origin URL WITHOUT any credential (the token is only read by publish.sh's helper).
# The engine's own atlas/ firsts/ journal/ (written there before the clone existed) are copied into the clone, local
# wins (they only grow); the old folder is kept as repo.old.<UTC>. Never done while the engine runs (it writes there).
say "S5b publication clone /var/lib/sol0/repo"
PUB_URL="https://github.com/$REPO.git"
[ -n "$ROOT" ] && [ -n "${SOL0_PUB_URL:-}" ] && PUB_URL="$SOL0_PUB_URL"     # tests only: a local bare repository
REPO_DIR=/var/lib/sol0/repo
repo_origin() { git config --file "$(p "$REPO_DIR")/.git/config" --get remote.origin.url 2>/dev/null || true; }
repo_check() { local o; o="$(repo_origin)"; [ "$o" = "$PUB_URL" ] || [ "$o.git" = "$PUB_URL" ]; }
repo_apply() {
  local full new old d
  full="$(p "$REPO_DIR")"; new="$full.new"; old="$full.old.$STAMP"
  rm -rf "$new"
  if [ -z "$ROOT" ]; then runuser -u sol0 -- env HOME=/var/lib/sol0 git clone --quiet --depth 1 -- "$PUB_URL" "$new"
  else git clone --quiet --depth 1 -- "$PUB_URL" "$new"; fi
  if [ -d "$full" ]; then
    for d in atlas firsts journal; do
      [ -d "$full/$d" ] || continue
      mkdir -p "$new/$d"; cp -pR "$full/$d/." "$new/$d/"
    done
    mv "$full" "$old"
    undo "$(printf 'note\t%s kept as %s (publication clone not reversed by rollback.sh)' "$full" "$old")"
  fi
  mv "$new" "$full"
  [ -z "$ROOT" ] && chown -R sol0:sol0 "$full"
  return 0
}
repo_has_git=0; [ -e "$(p "$REPO_DIR")/.git" ] && repo_has_git=1
if [ "$repo_has_git" = 1 ] && ! repo_check; then
  o="$(repo_origin)"; case "$o" in *@*) o="(an URL with credentials: remove them)" ;; esac
  say "  WARN  $REPO_DIR is a git clone with origin '${o:-none}', expected $PUB_URL: left as is."
  say "        Fix as sol0: runuser -u sol0 -- git -C $REPO_DIR remote set-url origin $PUB_URL"
elif [ "$repo_has_git" = 0 ] && [ -z "$ROOT" ] && [ -d "$REPO_DIR" ] && systemctl is-active --quiet rover-live 2>/dev/null; then
  say "  WARN  $REPO_DIR is not a git clone and the engine is running: not replaced now (docs/OPERATIONS.md, SEC-01)."
elif [ -n "$ROOT" ] && [ -z "${SOL0_PUB_URL:-}" ]; then
  act publication-clone "git clone --depth 1 $PUB_URL into $REPO_DIR as sol0 (no credential in the URL; atlas/ firsts/ journal/ kept)" repo_check repo_apply
elif ! repo_check; then
  plan_note "git clone --depth 1 $PUB_URL into $REPO_DIR as sol0 (no credential in the URL; atlas/ firsts/ journal/ kept)"
  if [ "$DRY" = 0 ]; then bk_init; repo_apply; fi
fi
if [ -z "$ROOT" ] && [ -e "$REPO_DIR/.git" ] && [ "$(stat -c %U "$REPO_DIR" 2>/dev/null)" != sol0 ]; then
  say "  WARN  $REPO_DIR is not owned by sol0: publication would fail (chown -R sol0:sol0 $REPO_DIR)"
fi

# ---- S5c `python` for publish.sh (SEC-01): the running engine has no PATH of its own (the unit's PATH applies at its
# next start), so /usr/local/bin/python -> /usr/bin/python3 (publish_lib.py needs the standard library only).
say "S5c python link for publish.sh"
PYLINK="$(p /usr/local/bin/python)"
if [ -L "$PYLINK" ] && [ "$(readlink "$PYLINK")" = /usr/bin/python3 ]; then :
elif [ -e "$PYLINK" ] || [ -L "$PYLINK" ]; then
  say "  WARN  /usr/local/bin/python exists and is not the link to /usr/bin/python3: left as is"
else
  ensure_dir /usr/local/bin 0755 root:root
  ensure_link /usr/local/bin/python /usr/bin/python3
fi

# ---- S6 units
say "S6 systemd units"
UNITS="rover-live.service rover-web.service sol0-reboot.service sol0-reboot.timer"
UNITS_CHANGED=0; UOLD=""
for u in $UNITS; do
  cmp -s "$KIT/units/$u" "$(p "/etc/systemd/system/$u")" 2>/dev/null || UNITS_CHANGED=1
  UOLD="$UOLD$(ck "$(p "/etc/systemd/system/$u")")-"
done
# A changed unit is checked by systemd BEFORE it is written (a bad unit would only show at the next start of the engine).
if [ "$UNITS_CHANGED" = 1 ] && [ -z "$ROOT" ] && [ "$DRY" = 0 ] && [ -z "${SOL0_SKIP_UNIT_VERIFY:-}" ]; then
  mkdir -p "$TMPD/units"; vf=()
  for u in $UNITS; do cp "$KIT/units/$u" "$TMPD/units/$u"; vf+=("$TMPD/units/$u"); done
  if ! systemd-analyze verify "${vf[@]}" >"$TMPD/verify.txt" 2>&1; then
    cat "$TMPD/verify.txt" >&2
    echo "S6: systemd-analyze verify refused the kit units: nothing written from S6 on (fix the kit, or SOL0_SKIP_UNIT_VERIFY=1 after reading the message)." >&2
    exit 1
  fi
fi
for u in $UNITS; do
  ensure_file "/etc/systemd/system/$u" 0644 root:root "$KIT/units/$u"
done
# set-property (Lot 0) writes runtime drop-ins that take precedence over these files: once the kit values are live
# (same values, SEC-04/SEC-24), they are removed by the operator, never by this script.
for f in "$(p /etc/systemd/system.control)"/rover-live.service.d/*.conf "$(p /etc/systemd/system.control)"/rover-web.service.d/*.conf \
         "$(p /etc/systemd/system.control)"/caddy.service.d/*.conf; do
  [ -e "$f" ] || continue
  say "  NOTE  runtime drop-in ${f#"$ROOT"} overrides the kit unit (set-property). When 'systemctl show' gives the kit value:"
  say "        rm ${f#"$ROOT"} ; systemctl daemon-reload   (docs/OPERATIONS.md, Lot 2)"
done
UCK="$(cat "${KIT}"/units/*.service "${KIT}"/units/*.timer | cksum | cut -d" " -f1)"
# Birth safety: the real engine must never start on an empty state. Until `sol0ctl birth --at <UTC ISO>` has written
# live/birth.json, rover-live is ENABLED BUT HELD by a drop-in (ExecCondition=/bin/false). install.sh never starts it.
if [ ! -e "$(p /var/lib/sol0/live/birth.json)" ]; then
  ensure_dir /etc/systemd/system/rover-live.service.d 0755 root:root
  ensure_file /etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf 0644 root:root "$KIT/units/00-hold-until-golive.conf"
else
  say "  birth record present: no hold drop-in is (re)created"
fi
# after the hold drop-in, so that systemd never sees the new units without it
ur_check() { [ "$UNITS_CHANGED" = 0 ]; }
ur_apply() { systemctl daemon-reload; }
if [ "$UNITS_CHANGED" = 1 ]; then
  act "units-reload-$UCK-$(printf '%s' "$UOLD" | cksum | cut -d" " -f1)" "systemctl daemon-reload (units changed: limits apply now, the engine's Environment at its next start; nothing restarted)" ur_check ur_apply
fi
sd_check() { systemctl is-enabled rover-live.service rover-web.service sol0-reboot.timer >/dev/null 2>&1 && systemctl is-active --quiet rover-web.service; }
sd_apply() { systemctl daemon-reload && systemctl enable rover-live.service && systemctl enable --now rover-web.service sol0-reboot.timer; }
act units-enable "systemctl daemon-reload; enable rover-live (held until birth, NOT started); enable --now rover-web, sol0-reboot.timer" sd_check sd_apply

# ---- S7 Caddy
say "S7 Caddyfile live.$DOMAIN (site-apex=$SITE_APEX canonical=$CANONICAL)"
if [ "$FLAGS_EXPLICIT" = 1 ]; then
  printf 'site_apex=%s\ncanonical=%s\n' "$SITE_APEX" "$CANONICAL" > "$TMPD/site.flags"
  ensure_file /etc/sol0/site.flags 0644 root:root "$TMPD/site.flags"
fi
# Content-Security-Policy sent as an HTTP header for the page and its 404 (SEC-15, SEC-29). Contract with the page
# (build_page.py, meta of index.html): same sources, the state only under https://raw.githubusercontent.com/<repo>/state/.
CSP="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' https://raw.githubusercontent.com/@REPO@/state/; media-src 'self'; connect-src 'self' https://live.@DOMAIN@ https://raw.githubusercontent.com/@REPO@/state/; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'"
# Render a template: the marker lines are replaced by fragments (nothing when the flag is off); fragments are rendered too.
render_tmpl() {
  local line
  while IFS= read -r line; do
    case "$line" in
      "@@LIVE_CORS@@") [ "$SITE_APEX" = on ] && cat "$KIT/caddy/frag-cors-apex.tmpl" ;;
      "@@LIVE_REST@@") if [ "$CANONICAL" = apex ]; then cat "$KIT/caddy/frag-live-redir.tmpl"; else cat "$KIT/caddy/frag-live-page.tmpl"; fi ;;
      "@@APEX@@") [ "$SITE_APEX" = on ] && render_tmpl "$KIT/caddy/Caddyfile.apex.tmpl" ;;
      "@@ERRORS@@") cat "$KIT/caddy/frag-errors.tmpl" ;;
      "@@HTTP@@") if [ "$SITE_APEX" = on ]; then hosts="http://live.@DOMAIN@, http://@DOMAIN@, http://www.@DOMAIN@"; else hosts="http://live.@DOMAIN@"; fi
                  sed "s|^@HTTPHOSTS@ {|$hosts {|" "$KIT/caddy/frag-http.tmpl" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < "$1"
  return 0
}
render_tmpl "$KIT/caddy/Caddyfile.tmpl" | sed -e "s|@CSP@|$CSP|g" -e "s|@REPO@|$REPO|g" -e "s/@DOMAIN@/$DOMAIN/g" > "$TMPD/Caddyfile"
# Small files served by Caddy itself (robots.txt of live., security.txt): lines marked @APEXONLY@ only with sol0.fr on.
render_site() { # render_site TEMPLATE -> stdout
  if [ "$SITE_APEX" = on ]; then sed 's/^@APEXONLY@//' "$1"; else grep -v '^@APEXONLY@' "$1"; fi \
    | sed -e "s|@REPO@|$REPO|g" -e "s/@DOMAIN@/$DOMAIN/g"
}
ensure_dir /opt/sol0/site-files 0755 root:root
render_site "$KIT/site/robots-live.txt.tmpl" > "$TMPD/robots-live.txt"
render_site "$KIT/site/security.txt.tmpl" > "$TMPD/security.txt"
ensure_file /opt/sol0/site-files/robots-live.txt 0644 root:root "$TMPD/robots-live.txt"
ensure_file /opt/sol0/site-files/security.txt 0644 root:root "$TMPD/security.txt"
SEC_EXPIRES="$(sed -n 's/^Expires: \([0-9-]*\)T.*/\1/p' "$TMPD/security.txt")"
ensure_dir /etc/caddy 0755 root:root
CADDY_CHANGED=0
CADDY_OLD=""; [ -f "$(p /etc/caddy/Caddyfile)" ] && CADDY_OLD="$(cksum < "$(p /etc/caddy/Caddyfile)" | cut -d" " -f1)"; CADDY_OLD="${CADDY_OLD:-none}"
cmp -s "$TMPD/Caddyfile" "$(p /etc/caddy/Caddyfile)" 2>/dev/null || CADDY_CHANGED=1
ensure_file /etc/caddy/Caddyfile 0644 root:root "$TMPD/Caddyfile"
# Confinement and CPU share of caddy.service (SEC-09, SEC-24): a drop-in, the package's unit is never edited.
CADDY_DROPIN=/etc/systemd/system/caddy.service.d/90-sol0-hardening.conf
CADDY_UNIT_CHANGED=0
cmp -s "$KIT/caddy/90-sol0-hardening.conf" "$(p "$CADDY_DROPIN")" 2>/dev/null || CADDY_UNIT_CHANGED=1
CADDY_DROPIN_OLD="$(ck "$(p "$CADDY_DROPIN")")"
ensure_dir /etc/systemd/system/caddy.service.d 0755 root:root
ensure_file "$CADDY_DROPIN" 0644 root:root "$KIT/caddy/90-sol0-hardening.conf"
# a changed Caddyfile is always (re)loaded: the package default config may already be valid and active (kit defect, 2026-11-12).
# The admin API is off (audit S-2), so `caddy reload` cannot work: restart (a brief cut of the stream).
# If caddy does not come back with the new confinement, the drop-in is set aside and caddy restarted without it (site
# first), then the run stops with the reason: journalctl -u caddy.
cd_check() { [ "$CADDY_CHANGED" = 0 ] && [ "$CADDY_UNIT_CHANGED" = 0 ] && caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 && systemctl is-active --quiet caddy; }
cd_apply() {
  caddy validate --config /etc/caddy/Caddyfile || return 1
  systemctl daemon-reload
  systemctl enable caddy
  if systemctl restart caddy && sleep 3 && systemctl is-active --quiet caddy; then return 0; fi
  echo "S7: caddy is not active after the restart: hardening drop-in set aside ($CADDY_DROPIN.failed), caddy restarted without it." >&2
  mv -f "$CADDY_DROPIN" "$CADDY_DROPIN.failed"; systemctl daemon-reload; systemctl restart caddy || true
  echo "S7: read journalctl -u caddy -n 50 ; the site runs without the confinement until the kit is fixed." >&2
  return 1
}
if [ -n "$ROOT" ] && [ "$CADDY_CHANGED" = 0 ] && [ "$CADDY_UNIT_CHANGED" = 0 ]; then :   # simulated root: nothing to reload
else
  act "caddy-reload-$(cat "$TMPD/Caddyfile" "$KIT/caddy/90-sol0-hardening.conf" | cksum | cut -d" " -f1)-${CADDY_OLD:-none}-$CADDY_DROPIN_OLD" "caddy validate, then restart (Caddyfile or caddy confinement changed, or caddy not active)" cd_check cd_apply
fi

# ---- S8 firewall (22 first)
say "S8 ufw (22, 80, 443)"
# SSH is LIMITed (SEC-25: 6 new connections in 30 s per address at most; operators use one session or ControlMaster).
# The check wants LIMIT and no ALLOW left on 22/tcp: an old ALLOW listed first would win over the LIMIT rule.
uf_check() {
  local s; s="$(ufw status 2>/dev/null)" || return 1
  grep -q "Status: active" <<<"$s" && grep -q '^443/tcp' <<<"$s" && grep -q '^80/tcp' <<<"$s" \
    && grep -Eq '^22/tcp +LIMIT' <<<"$s" && ! grep -Eq '^22/tcp( \(v6\))? +ALLOW' <<<"$s"
}
uf_apply() {
  ufw limit 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw default deny incoming && ufw default allow outgoing
  if ufw status | grep -Eq '^22/tcp( \(v6\))? +ALLOW'; then ufw --force delete allow 22/tcp; fi   # the LIMIT rule is already in place
  ufw --force enable
}
act ufw "ufw limit 22/tcp (no ALLOW left on 22), allow 80,443/tcp; deny other inbound; enable" uf_check uf_apply

# ---- S9 SSH, only with a key and a valid config
say "S9 SSH key-only"
AK="$(p /root/.ssh/authorized_keys)"
if [ -s "$AK" ]; then
  ensure_dir /etc/ssh/sshd_config.d 0755 root:root
  SSHD_CHANGED=0
  cmp -s "$KIT/sshd/10-sol0.conf" "$(p /etc/ssh/sshd_config.d/10-sol0.conf)" 2>/dev/null || SSHD_CHANGED=1
  SSHD_OLD="$(ck "$(p /etc/ssh/sshd_config.d/10-sol0.conf)")"
  ensure_file /etc/ssh/sshd_config.d/10-sol0.conf 0644 root:root "$KIT/sshd/10-sol0.conf"
  # effective values (sshd -T), not only the file: a changed file is always reloaded (open sessions are kept)
  ss_check() {
    local e; [ "$SSHD_CHANGED" = 0 ] && sshd -t >/dev/null 2>&1 && e="$(sshd -T 2>/dev/null)" || return 1
    grep -qx "passwordauthentication no" <<<"$e" && grep -qx "allowagentforwarding no" <<<"$e" && grep -qx "allowusers root" <<<"$e"
  }
  ss_apply() { sshd -t && systemctl reload ssh; }
  if [ -n "$ROOT" ] && [ "$SSHD_CHANGED" = 0 ]; then :
  else act "sshd-$(cksum < "$KIT/sshd/10-sol0.conf" | cut -d" " -f1)-$SSHD_OLD" "sshd -t then reload ssh (key only, no agent forwarding, AllowUsers root sol0ops)" ss_check ss_apply; fi
else
  say "  SKIP  authorized_keys empty: SSH left as is (add a key, then run again)"
fi
# cloud-init would write PasswordAuthentication back from its own setting (SEC-25): set it off where cloud-init exists.
if [ -d "$(p /etc/cloud)" ]; then
  ensure_dir /etc/cloud/cloud.cfg.d 0755 root:root
  ensure_file /etc/cloud/cloud.cfg.d/99-sol0.cfg 0644 root:root "$KIT/cloud/99-sol0.cfg"
fi

# ---- S9b sol0ops: read-only operator account for agents and checks (SEC-03). Its key can only run sol0-status (forced
# command, no shell, no pty, no forwarding). Member of group sol0 to read live/*.json (the token stays 0700 sol0).
# root login is kept until the owner switches. The key: --ops-key FILE (public key); kept when the option is omitted.
say "S9b sol0ops (read-only report over SSH)"
op_check() { id sol0ops >/dev/null 2>&1 && id -nG sol0ops | tr ' ' '\n' | grep -qx sol0; }
op_apply() {
  id sol0ops >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/sol0ops --shell /bin/sh sol0ops
  usermod -a -G sol0 sol0ops
}
act sol0ops-user "user sol0ops (home /var/lib/sol0ops, password locked, group sol0 for reading)" op_check op_apply
ensure_dir /var/lib/sol0ops 0750 sol0ops:sol0ops
ensure_dir /var/lib/sol0ops/.ssh 0700 sol0ops:sol0ops
if [ -n "$OPS_KEY_LINE" ]; then
  printf 'restrict,command="/usr/local/bin/sol0-status" %s\n' "$OPS_KEY_LINE" > "$TMPD/ops_keys"
  ensure_file /var/lib/sol0ops/.ssh/authorized_keys 0600 sol0ops:sol0ops "$TMPD/ops_keys"
elif [ ! -s "$(p /var/lib/sol0ops/.ssh/authorized_keys)" ]; then
  say "  SKIP  no --ops-key and no key yet: sol0ops cannot log in (give --ops-key FILE.pub, then run again)"
fi

# ---- S10 updates, journald, logrotate
say "S10 unattended-upgrades, journald, logrotate"
ensure_file /etc/apt/apt.conf.d/52sol0-unattended 0644 root:root "$KIT/apt/52sol0-unattended"
ensure_dir /etc/systemd/journald.conf.d 0755 root:root
ensure_file /etc/systemd/journald.conf.d/90-sol0.conf 0644 root:root "$KIT/journald/90-sol0.conf"
ensure_file /etc/logrotate.d/sol0 0644 root:root "$KIT/logrotate/sol0"
jd_check() { [ "$(systemctl show -p ActiveEnterTimestampMonotonic systemd-journald --value 2>/dev/null)" -gt 0 ] 2>/dev/null && journalctl --disk-usage 2>&1 | grep -q 'M' ; }
jd_apply() { systemctl restart systemd-journald; }
act journald-restart "restart journald to apply SystemMaxUse=200M" jd_check jd_apply
# Operator tools come from the kit that ran (not from the engine release, which changes only with the engine).
ensure_dir /opt/sol0/kit 0755 root:root
for f in sol0ctl sol0-status healthcheck.sh ntp_check.sh; do
  ensure_file "/opt/sol0/kit/$f" 0755 root:root "$KIT/$f"
done
ensure_dir /usr/local/sbin 0755 root:root
ensure_link /usr/local/sbin/sol0ctl /opt/sol0/kit/sol0ctl
ensure_dir /usr/local/bin 0755 root:root
ensure_link /usr/local/bin/sol0-status /opt/sol0/kit/sol0-status

# ---- S11 report
# no change: drop the empty backup set
if [ "$DRY" = 0 ] && [ "$CHANGES" = 0 ] && [ -n "$BK" ]; then rm -rf "$BK"; fi
say "S11 report"
if [ -e "$(p /var/lib/sol0/secret/github-token)" ]; then say "  token: present"; else
  say "  token: missing. Next command to type: sol0ctl token set   (publication stays 'off' until the owner enables it)"; fi
say "  check: tools/server/healthcheck.sh ; curl -sSI https://live.$DOMAIN/health"
# security.txt must not expire (RFC 9116): warn 60 days before (the date is in tools/server/site/security.txt.tmpl)
if [ -n "$SEC_EXPIRES" ]; then
  exp_s="$(date -u -d "$SEC_EXPIRES" +%s 2>/dev/null || date -u -j -f %Y-%m-%d "$SEC_EXPIRES" +%s 2>/dev/null || echo 0)"
  now_s="${SOL0_NOW_EPOCH:-$(date -u +%s)}"
  if [ "$exp_s" -gt 0 ] && [ $((exp_s - now_s)) -lt $((60 * 86400)) ]; then
    say "  WARN  security.txt expires on $SEC_EXPIRES: move Expires (at most one year ahead) in tools/server/site/security.txt.tmpl"
  fi
fi
report
# no change: drop the empty backup set
if [ "$DRY" = 0 ] && [ "$CHANGES" = 0 ] && [ -n "$BK" ]; then rm -rf "$BK"; fi
