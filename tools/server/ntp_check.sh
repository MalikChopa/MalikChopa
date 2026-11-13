#!/usr/bin/env bash
# Exit 0 only if the system clock is NTP-synchronised. Used by rover-live.service (ExecStartPre) and `sol0ctl birth`:
# the birth seed and the 15-minute slots rest on the real clock (audit S-6).
v="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
if [ "$v" = yes ]; then exit 0; fi
echo "ntp_check: system clock not synchronised (NTPSynchronized='$v'); engine start refused" >&2
exit 1
