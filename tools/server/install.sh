#!/usr/bin/env bash
# Sol-0 live server kit. Target: Ubuntu 24.04 LTS x86-64 (any VPS; deployed on Contabo). Run as root.
# Idempotent: every step plans, then applies. --dry-run lists and touches nothing.
# --root DIR works on a copy of the tree (tests on the Mac): system actions are simulated.
# Never reads, prints or stores a token: see `sol0ctl token set`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE"
ROOT=""; DRY=0; DOMAIN=""; PAGES_ORIGIN=""; REPO=""; SHA=""; SRC=""
usage() { echo "usage: install.sh [--dry-run] [--root DIR] --domain D --pages-origin URL --repo OWNER/NAME --sha COMMIT [--src GIT_URL_OR_DIR]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --root) ROOT="${2:?}"; shift ;;
    --domain) DOMAIN="${2:?}"; shift ;;
    --pages-origin) PAGES_ORIGIN="${2:?}"; shift ;;
    --repo) REPO="${2:?}"; shift ;;
    --sha) SHA="${2:?}"; shift ;;
    --src) SRC="${2:?}"; shift ;;
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
[ -z "$SRC" ] && SRC="https://github.com/$REPO.git"
[ -n "$ROOT" ] && { [ -d "$ROOT" ] || { echo "--root: not a directory" >&2; exit 2; }; }
[ -z "$ROOT" ] && [ "$(id -u)" != 0 ] && [ "$DRY" = 0 ] && { echo "run as root (or use --dry-run / --root)" >&2; exit 2; }

# shellcheck source=lib/plan.sh
. "$HERE/lib/plan.sh"
STAMP="${SOL0_NOW:-$(date -u +%Y%m%dT%H%M%SZ)}"
TMPD="$(mktemp -d)"; trap 'rm -rf "$TMPD"' EXIT

[ "$DRY" = 0 ] && bk_init
say "Sol-0 install ($([ "$DRY" = 1 ] && echo dry-run || echo apply)) root='${ROOT:-/}' domain=live.$DOMAIN sha=$SHA"

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

# ---- S6 units
say "S6 systemd units"
for u in rover-live.service rover-web.service sol0-reboot.service sol0-reboot.timer; do
  ensure_file "/etc/systemd/system/$u" 0644 root:root "$KIT/units/$u"
done
# Birth safety: the real engine must never start on an empty state. Until `sol0ctl birth --at <UTC ISO>` has written
# live/birth.json, rover-live is ENABLED BUT HELD by a drop-in (ExecCondition=/bin/false). install.sh never starts it.
if [ ! -e "$(p /var/lib/sol0/live/birth.json)" ]; then
  ensure_dir /etc/systemd/system/rover-live.service.d 0755 root:root
  ensure_file /etc/systemd/system/rover-live.service.d/00-hold-until-golive.conf 0644 root:root "$KIT/units/00-hold-until-golive.conf"
else
  say "  birth record present: no hold drop-in is (re)created"
fi
sd_check() { systemctl is-enabled rover-live.service rover-web.service sol0-reboot.timer >/dev/null 2>&1 && systemctl is-active --quiet rover-web.service; }
sd_apply() { systemctl daemon-reload && systemctl enable rover-live.service && systemctl enable --now rover-web.service sol0-reboot.timer; }
act units-enable "systemctl daemon-reload; enable rover-live (held until birth, NOT started); enable --now rover-web, sol0-reboot.timer" sd_check sd_apply

# ---- S7 Caddy
say "S7 Caddyfile live.$DOMAIN"
sed "s/@DOMAIN@/$DOMAIN/g" "$KIT/caddy/Caddyfile.tmpl" > "$TMPD/Caddyfile"
ensure_dir /etc/caddy 0755 root:root
CADDY_CHANGED=0
CADDY_OLD="$(cksum < "$(p /etc/caddy/Caddyfile)" 2>/dev/null | cut -d" " -f1 || true)"; CADDY_OLD="${CADDY_OLD:-none}"
cmp -s "$TMPD/Caddyfile" "$(p /etc/caddy/Caddyfile)" 2>/dev/null || CADDY_CHANGED=1
ensure_file /etc/caddy/Caddyfile 0644 root:root "$TMPD/Caddyfile"
# a changed Caddyfile is always (re)loaded: the package default config may already be valid and active (kit defect, 2026-11-12).
# The admin API is off (audit S-2), so `caddy reload` cannot work: restart (a brief cut of the stream).
cd_check() { [ "$CADDY_CHANGED" = 0 ] && caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 && systemctl is-active --quiet caddy; }
cd_apply() { caddy validate --config /etc/caddy/Caddyfile && systemctl enable caddy && systemctl restart caddy; }
if [ -n "$ROOT" ] && [ "$CADDY_CHANGED" = 0 ]; then :   # simulated root: nothing to reload when the file did not change
else
  act "caddy-reload-$(cksum < "$TMPD/Caddyfile" | cut -d" " -f1)-${CADDY_OLD:-none}" "caddy validate, then restart (Caddyfile changed or caddy not active)" cd_check cd_apply
fi

# ---- S8 firewall (22 first)
say "S8 ufw (22, 80, 443)"
uf_check() { ufw status 2>/dev/null | grep -q "Status: active" && ufw status | grep -q '^443/tcp' && ufw status | grep -q '^22/tcp'; }
uf_apply() { ufw limit 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw default deny incoming && ufw default allow outgoing && ufw --force enable; }
act ufw "ufw allow 22,80,443/tcp; deny other inbound; enable" uf_check uf_apply

# ---- S9 SSH, only with a key and a valid config
say "S9 SSH key-only"
AK="$(p /root/.ssh/authorized_keys)"
if [ -s "$AK" ]; then
  ensure_dir /etc/ssh/sshd_config.d 0755 root:root
  ensure_file /etc/ssh/sshd_config.d/10-sol0.conf 0644 root:root "$KIT/sshd/10-sol0.conf"
  ss_check() { sshd -t >/dev/null 2>&1 && grep -q "passwordauthentication no" <(sshd -T 2>/dev/null); }
  ss_apply() { sshd -t && systemctl reload ssh; }
  act sshd "sshd -t then reload ssh" ss_check ss_apply
else
  say "  SKIP  authorized_keys empty: SSH left as is (add a key, then run again)"
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
ensure_dir /usr/local/sbin 0755 root:root
ensure_link /usr/local/sbin/sol0ctl /opt/sol0/app/tools/server/sol0ctl

# ---- S11 report
# no change: drop the empty backup set
if [ "$DRY" = 0 ] && [ "$CHANGES" = 0 ] && [ -n "$BK" ]; then rm -rf "$BK"; fi
say "S11 report"
if [ -e "$(p /var/lib/sol0/secret/github-token)" ]; then say "  token: present"; else
  say "  token: missing. Next command to type: sol0ctl token set   (publication stays 'off' until the owner enables it)"; fi
say "  check: tools/server/healthcheck.sh ; curl -sSI https://live.$DOMAIN/health"
report
# no change: drop the empty backup set
if [ "$DRY" = 0 ] && [ "$CHANGES" = 0 ] && [ -n "$BK" ]; then rm -rf "$BK"; fi
