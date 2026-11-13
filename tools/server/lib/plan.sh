# shellcheck shell=bash
# Plan/apply helpers for install.sh and rollback.sh. Sourced, never executed.
# Globals: ROOT (prefix, empty on the real server), DRY (0/1), CHANGES, BK (backup dir), TMPD.

CHANGES=0
BK=""

p() { printf '%s%s' "$ROOT" "$1"; }          # real path under the prefix
say() { printf '%s\n' "$*"; }

fmode() { # octal mode of a path, Linux or macOS
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

plan_note() { # one planned or applied change
  CHANGES=$((CHANGES + 1))
  if [ "$DRY" = 1 ]; then say "  PLAN  $*"; else say "  DO    $*"; fi
}

bk_init() { # lazily create the backup dir (never in dry run)
  [ "$DRY" = 1 ] && return 0
  if [ -z "$BK" ]; then
    BK="$(p /var/backups/sol0)/$STAMP"
    mkdir -p "$BK/files"
    : >> "$BK/undo.log"
  fi
}

undo() { # undo "<verb>" fields... (tab separated)
  [ "$DRY" = 1 ] && return 0
  bk_init
  local IFS=$'\t'
  printf '%s\n' "$*" >> "$BK/undo.log"
}

bk_copy() { # back up an existing path, print its backup name
  local src="$1" name
  name="$(printf '%s' "$src" | tr '/' '_')"
  cp -p "$src" "$BK/files/$name"
  printf '%s' "$BK/files/$name"
}

ensure_dir() { # ensure_dir ABSPATH MODE OWNER:GROUP
  local path="$1" mode="$2" owner="$3" full parent
  full="$(p "$path")"
  if [ ! -d "$full" ]; then
    plan_note "mkdir $path ($mode $owner)"
    [ "$DRY" = 1 ] && return 0
    parent="$(dirname "$path")"
    [ "$parent" != "/" ] && [ ! -d "$(p "$parent")" ] && ensure_dir "$parent" 0755 root:root
    bk_init
    mkdir "$full"
    undo "$(printf 'rmdir\t%s' "$full")"
  else
    [ "$DRY" = 1 ] && return 0
  fi
  if [ -d "$full" ] && [ "$DRY" = 0 ]; then
    [ -z "$ROOT" ] && chown "$owner" "$full" 2>/dev/null
    chmod "$mode" "$full"                       # after chown: setgid (2750) must survive
  fi
  return 0
}

ensure_file() { # ensure_file ABSPATH MODE OWNER:GROUP SRCFILE
  local path="$1" mode="$2" owner="$3" src="$4" full old
  full="$(p "$path")"
  if [ -f "$full" ] && cmp -s "$src" "$full" && [ "$(fmode "$full")" = "${mode#0}" ]; then
    return 0
  fi
  plan_note "file $path ($mode)"
  [ "$DRY" = 1 ] && return 0
  [ -d "$(dirname "$full")" ] || ensure_dir "$(dirname "$path")" 0755 root:root
  bk_init
  if [ -e "$full" ]; then
    old="$(bk_copy "$full")"
    undo "$(printf 'restore\t%s\t%s' "$full" "$old")"
  else
    undo "$(printf 'remove\t%s' "$full")"
  fi
  cp "$src" "$full.new.$$" && chmod "$mode" "$full.new.$$"
  [ -z "$ROOT" ] && chown "$owner" "$full.new.$$" 2>/dev/null
  mv -f "$full.new.$$" "$full"
}

ensure_link() { # ensure_link ABSPATH TARGET
  local path="$1" target="$2" full cur
  full="$(p "$path")"
  cur="$(readlink "$full" 2>/dev/null || true)"
  [ "$cur" = "$target" ] && return 0
  plan_note "link $path -> $target"
  [ "$DRY" = 1 ] && return 0
  bk_init
  if [ -L "$full" ]; then
    undo "$(printf 'relink\t%s\t%s' "$full" "$cur")"
  else
    undo "$(printf 'remove\t%s' "$full")"
  fi
  ln -sfn "$target" "$full"
}

# act KEY DESC CHECKFN APPLYFN : a system action (apt, useradd, ufw, systemctl...).
# On the real server CHECKFN tells whether it is already done. Under --root nothing system-wide
# runs: a marker file in $ROOT/var/lib/sol0-install/ stands for the state (so pass 2 = 0 change).
act() {
  local key="$1" desc="$2" check="$3" apply="$4" mk
  mk="$(p /var/lib/sol0-install/$key)"
  if [ -n "$ROOT" ]; then
    [ -e "$mk" ] && return 0
    plan_note "$desc [simulated under --root]"
    [ "$DRY" = 1 ] && return 0
    ensure_dir /var/lib/sol0-install 0755 root:root
    bk_init
    : > "$mk"
    undo "$(printf 'remove\t%s' "$mk")"
    return 0
  fi
  "$check" && return 0
  plan_note "$desc"
  [ "$DRY" = 1 ] && return 0
  bk_init
  undo "$(printf 'note\t%s (not reversed by rollback.sh)' "$desc")"
  "$apply"
}

report() {
  if [ "$CHANGES" = 0 ]; then say "0 changement"; else say "$CHANGES changement(s)"; fi
}
