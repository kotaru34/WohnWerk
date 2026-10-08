#!/usr/bin/env bash
# Exact SHA-only WohnWerk recovery/deploy helper; sudo may pass recover|deploy only.
set -Eeuo pipefail
umask 022
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
APP=/opt/wohnwerk
BASE=83632033dbb4c4017ad8a3aba170bc94d63f8ba8
TARGET=31451e873310cda471833bed36fbc3f6718fa35f
ROLLBACK=refs/wohnwerk/rollback-v0.4.27-pre-v0.4.28
RULE=/etc/sudoers.d/91-wohnwerk-v0428-maintain
gitw() { /usr/bin/git -c safe.directory=/opt/wohnwerk -c core.hooksPath=/dev/null -C "$APP" "$@"; }
[[ "$EUID" == 0 && "$#" -eq 1 ]] || exit 64
case "$1" in recover|deploy) ACTION="$1" ;; *) exit 64 ;; esac
[[ -d "$APP/.git" && -x /usr/bin/flock ]] || exit 1
exec 9>/run/lock/wohnwerk-v0428-maintain.lock
/usr/bin/flock -n 9 || { echo 'Another maintenance operation is running' >&2; exit 75; }

head_sha() { gitw rev-parse HEAD; }
check_clean() { [[ -z "$(gitw status --porcelain)" ]]; }
check_health() {
    local want="$1" success=1
    for ((i=0;i<20;i++)); do
        if /usr/bin/python3 - "$want" <<'PY'
import json,sys,urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3) as r:
        h=json.load(r)
except (OSError,ValueError):
    sys.exit(1)
assert h.get('status')=='ok' and h.get('version')==sys.argv[1]
PY
        then
            success=0
            break
        fi
        /usr/bin/sleep 2
    done
    return "$success"
}
# Restrict permission repair to tracked files changed between approved SHAs.
repair_modes() {
    local rev="$1" file mode
    gitw cat-file -e "$BASE^{commit}"
    gitw cat-file -e "$TARGET^{commit}"
    while IFS= read -r -d '' file; do
        [[ -f "$APP/$file" ]] || continue
        mode="$(gitw ls-tree "$rev" -- "$file" | /usr/bin/awk 'NR==1 {print $1}')"
        case "$mode" in
            100644) /usr/bin/chmod 0644 -- "$APP/$file" ;;
            100755) /usr/bin/chmod 0755 -- "$APP/$file" ;;
            '') ;;
            *) echo "Unexpected file mode for $file: $mode" >&2; return 1 ;;
        esac
    done < <(gitw diff --name-only -z "$BASE" "$TARGET")
    [[ -f "$APP/.git/HEAD" ]] && /usr/bin/chmod 0644 "$APP/.git/HEAD"
    [[ -f "$APP/.git/index" ]] && /usr/bin/chmod 0644 "$APP/.git/index"
}
if [[ "$ACTION" == recover ]]; then
    [[ "$(head_sha)" == "$BASE" ]] || { echo 'Unexpected HEAD' >&2; exit 1; }
    /usr/bin/systemctl stop wohnwerk-refresh.timer
    repair_modes "$BASE"
    check_clean || { echo 'Dirty worktree after recovery' >&2; exit 1; }
    /usr/bin/systemctl restart wohnwerk.service
    if ! check_health 0.4.27; then
        echo 'RECOVER FAILED; timer stopped; recovery still allowed' >&2
        exit 1
    fi
    /usr/bin/systemctl start wohnwerk-refresh.timer
    /usr/bin/systemctl is-active --quiet wohnwerk.service
    /usr/bin/systemctl is-active --quiet wohnwerk-refresh.timer
    echo "RECOVER SUCCESS: v0.4.27 $(head_sha)"
    exit 0
fi
[[ "$(head_sha)" == "$BASE" ]] || { echo 'Wrong starting HEAD' >&2; exit 1; }
check_clean || { echo 'Dirty worktree' >&2; exit 1; }
/usr/bin/systemctl is-active --quiet wohnwerk.service
/usr/bin/systemctl is-active --quiet wohnwerk-refresh.timer
! /usr/bin/systemctl is-active --quiet wohnwerk-refresh.service || {
    echo 'Refresh running; refuse deployment' >&2; exit 1;
}
check_health 0.4.27 || { echo 'Base unhealthy; recover first' >&2; exit 1; }
gitw fetch --no-tags origin refs/heads/release/v0.4.28
[[ "$(gitw rev-parse FETCH_HEAD)" == "$TARGET" ]] || {
    echo 'Release branch moved from approved SHA' >&2; exit 1;
}
if gitw show-ref --verify --quiet "$ROLLBACK"; then
    [[ "$(gitw rev-parse "$ROLLBACK")" == "$BASE" ]] || exit 1
else
    gitw update-ref "$ROLLBACK" "$BASE" 0000000000000000000000000000000000000000
fi
changed_checkout=0
rollback_on_failure() {
    local rc="$?"
    trap - EXIT
    if (( rc == 0 )); then return 0; fi
    echo "Deploy failed (rc=$rc); restoring v0.4.27" >&2
    if (( changed_checkout )); then
        gitw checkout --detach "$BASE" || true
        repair_modes "$BASE" || true
        /usr/bin/systemctl restart wohnwerk.service || true
    fi
    if check_health 0.4.27; then
        /usr/bin/systemctl start wohnwerk-refresh.timer || true
        echo 'ROLLBACK HEALTHY: v0.4.27' >&2
    else
        echo 'ROLLBACK UNHEALTHY: timer stopped, recovery still allowed' >&2
    fi
    exit "$rc"
}
trap rollback_on_failure EXIT
/usr/bin/systemctl stop wohnwerk-refresh.timer
/usr/bin/systemctl stop wohnwerk.service
changed_checkout=1
gitw checkout --detach "$TARGET"
repair_modes "$TARGET"
[[ "$(head_sha)" == "$TARGET" ]] && check_clean
/usr/bin/systemctl start wohnwerk.service
check_health 0.4.28 || { echo 'Target health failed' >&2; exit 1; }
/usr/bin/systemctl start wohnwerk-refresh.timer
/usr/bin/systemctl is-active --quiet wohnwerk.service
/usr/bin/systemctl is-active --quiet wohnwerk-refresh.timer
# Self-revoke only on validated successful deployment; retain recovery on failure.
/usr/bin/rm -f -- "$RULE"
trap - EXIT
echo "DEPLOY SUCCESS: v0.4.28 $(head_sha)"
echo "Rollback: $ROLLBACK"
