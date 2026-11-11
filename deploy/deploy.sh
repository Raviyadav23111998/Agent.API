#!/usr/bin/env bash
#
# Ship a build of the Storeglance Agent API + gateway onto this host.
# Run as root on the server (CI does this over SSH):
#
#   deploy/deploy.sh <uat|prod> /tmp/agent-api.tar.gz
#
# The tarball holds the Agent.API tree with Agent.Core under core/ (the same
# layout the services' PYTHONPATH expects). The new tree is staged next to the
# live one, its requirements are installed into the environment's own venv,
# then it is swapped in and both services are restarted. If /health does not
# come back, the previous tree is restored.

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
ENV=${1:-}; TARBALL=${2:-}
case "$ENV" in uat|prod) ;; *) echo "usage: $0 <uat|prod> <tarball>" >&2; exit 2;; esac
[ -f "$TARBALL" ] || { echo "no tarball: $TARBALL" >&2; exit 2; }

if [ "$ENV" = prod ]; then HOST=ai.storeglance.com;     PFX="";     PORT=8130
else                       HOST=uat-ai.storeglance.com; PFX="uat-"; PORT=8131; fi
ROOT=/var/www/$HOST
API_UNIT=${PFX}storeglance-agent-api.service
GW_UNIT=${PFX}storeglance-agent-gateway.service

[ -f "/etc/storeglance/$ENV/agent/.env" ] || { echo "missing /etc/storeglance/$ENV/agent/.env — run deploy/db/provision.sh $ENV" >&2; exit 1; }
[ -x "$ROOT/venv/bin/python" ] || { echo "missing $ROOT/venv — run deploy/setup-server.sh" >&2; exit 1; }

# ── stage ────────────────────────────────────────────────────────────────
rm -rf "$ROOT/api.next"; mkdir -p "$ROOT/api.next"
tar -xzf "$TARBALL" -C "$ROOT/api.next"
[ -f "$ROOT/api.next/api/main.py" ] && [ -d "$ROOT/api.next/core/core" ] || {
    echo "tarball layout wrong: need api/main.py and core/core/" >&2; exit 1; }

# ── dependencies (only when the requirement files changed) ───────────────
REQS=$(cat "$ROOT/api.next/requirements.txt" "$ROOT/api.next/core/requirements.txt" 2>/dev/null | sha256sum | cut -c1-16)
if [ "$(cat "$ROOT/venv/.reqs" 2>/dev/null)" != "$REQS" ]; then
    echo "pip       installing requirements"
    "$ROOT/venv/bin/pip" install -q -r "$ROOT/api.next/requirements.txt"
    [ -f "$ROOT/api.next/core/requirements.txt" ] && "$ROOT/venv/bin/pip" install -q -r "$ROOT/api.next/core/requirements.txt"
    echo "$REQS" > "$ROOT/venv/.reqs"
else
    echo "pip       requirements unchanged"
fi

# ── swap ─────────────────────────────────────────────────────────────────
# Runtime state the app keeps in its working directory survives the swap.
[ -d "$ROOT/api/.ag_data" ] && cp -a "$ROOT/api/.ag_data" "$ROOT/api.next/"
chown -R sgagent:sgagent "$ROOT/api.next"
rm -rf "$ROOT/api.previous"
[ -d "$ROOT/api" ] && mv "$ROOT/api" "$ROOT/api.previous"
mv "$ROOT/api.next" "$ROOT/api"
systemctl restart "$API_UNIT" "$GW_UNIT"

# ── verify, or roll back ─────────────────────────────────────────────────
code=000
for _ in $(seq 1 24); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT/health" || true)
    [ "$code" = 200 ] && break
    sleep 5
done
if [ "$code" != 200 ]; then
    echo "FAILED    $API_UNIT /health=$code" >&2
    journalctl -u "$API_UNIT" -n 40 --no-pager >&2 || true
    if [ -d "$ROOT/api.previous" ]; then
        rm -rf "$ROOT/api.failed"; mv "$ROOT/api" "$ROOT/api.failed"; mv "$ROOT/api.previous" "$ROOT/api"
        systemctl restart "$API_UNIT" "$GW_UNIT"; echo "rolled back to the previous build" >&2
    fi
    exit 1
fi
systemctl is-active --quiet "$GW_UNIT" || echo "WARNING: $GW_UNIT is not active — check: journalctl -u $GW_UNIT" >&2
echo "deployed  $ENV ($HOST) — /health 200"
