#!/usr/bin/env bash
#
# One-time (and safe to re-run) host setup for the Storeglance Agent.
# Run as root on the server from a checkout of this repo's deploy/ folder:
#
#   deploy/setup-server.sh
#
# Creates the sgagent service account, the web/api roots and state dirs, the
# Python virtualenvs, the dedicated Neo4j container, the systemd units and —
# once their certificates exist — the nginx vhosts.
#
# It does NOT create databases or secrets (deploy/db/provision.sh does) and it
# does NOT ship code (deploy/deploy.sh does, from CI).
#
# Standalone by design: nothing here talks to MSystem or to any other product's
# database, Redis DB index, Elasticsearch index or Neo4j instance.

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP=$(date +%s)
BACKUP=/etc/nginx/backups/storeglance-agent.$STAMP

# ── service account ───────────────────────────────────────────────────────
if id sgagent >/dev/null 2>&1; then
    echo "user      sgagent exists"
else
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin sgagent
    echo "user      sgagent created"
fi

install_file() {   # src dst mode — copy only when different, backing up the old one
    local src=$1 dst=$2 mode=$3
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then echo "same      $dst"; return 1; fi
    if [ -f "$dst" ]; then install -d "$BACKUP"; cp -a "$dst" "$BACKUP/"; fi
    install -m "$mode" -o root -g root "$src" "$dst"
    echo "installed $dst"
}

# ── dedicated Neo4j ───────────────────────────────────────────────────────
# The agent exposes a raw-Cypher tool, so a shared Neo4j would let it read other
# products' graphs. One small instance for Storeglance; prod and uat are kept
# apart inside it by graph key (AG_DATA_NAMESPACE).
install -d -m 750 -o root -g root /etc/storeglance
NEO_ENV=/etc/storeglance/neo4j.env
if [ ! -f "$NEO_ENV" ]; then
    umask 077
    printf 'NEO4J_PASSWORD=%s\n' "$(openssl rand -hex 24)" > "$NEO_ENV"
    umask 022
    echo "neo4j     password generated in $NEO_ENV"
fi
# shellcheck disable=SC1090
. "$NEO_ENV"
if docker ps -a --format '{{.Names}}' | grep -qx storeglance-neo4j; then
    docker start storeglance-neo4j >/dev/null && echo "neo4j     storeglance-neo4j running"
else
    docker run -d --name storeglance-neo4j --restart unless-stopped \
        -p 127.0.0.1:7688:7687 -p 127.0.0.1:7475:7474 \
        -e NEO4J_AUTH="neo4j/$NEO4J_PASSWORD" \
        -e NEO4J_server_memory_heap_initial__size=256m \
        -e NEO4J_server_memory_heap_max__size=512m \
        -e NEO4J_server_memory_pagecache_size=256m \
        -v storeglance-neo4j-data:/data \
        neo4j:5-community >/dev/null
    echo "neo4j     storeglance-neo4j created (bolt 127.0.0.1:7688, http 127.0.0.1:7475)"
fi

# ── environments ──────────────────────────────────────────────────────────
units_changed=0
nginx_changed=0
installed_hosts=()
for ENV in uat prod; do
    if [ "$ENV" = prod ]; then HOST=ai.storeglance.com; PFX=""
    else                       HOST=uat-ai.storeglance.com; PFX="uat-"; fi
    ROOT=/var/www/$HOST
    STATE=/var/lib/storeglance-agent/$ENV

    install -d -m 755 -o root    -g root    "$ROOT"
    install -d -m 755 -o sgagent -g sgagent "$ROOT/api"
    install -d -m 755 -o root    -g root    "$ROOT/web"
    install -d -m 750 -o sgagent -g sgagent "$STATE" "$STATE/media"
    install -d -m 755 -o root -g root /var/lib/storeglance-agent/vsix /var/lib/storeglance-agent/vsix/vscode /var/lib/storeglance-agent/vsix/visualstudio
    [ -f "$ROOT/web/index.html" ] || cat > "$ROOT/web/index.html" <<HTML
<!doctype html><meta charset="utf-8"><title>Storeglance Agent</title>
<p>Storeglance Agent is being deployed.</p>
HTML

    # Own virtualenv per environment: the host's global Python packages belong
    # to other products and must never be upgraded by this one.
    if [ ! -x "$ROOT/venv/bin/python" ]; then
        python3 -m venv "$ROOT/venv"
        "$ROOT/venv/bin/pip" install -q --upgrade pip
        echo "venv      created $ROOT/venv"
    fi

    [ -f "/etc/storeglance/$ENV/agent/.env" ] || \
        echo "WARNING: /etc/storeglance/$ENV/agent/.env missing — run deploy/db/provision.sh $ENV" >&2

    for KIND in api gateway; do
        install_file "$HERE/systemd/${PFX}storeglance-agent-$KIND.service" \
            "/etc/systemd/system/${PFX}storeglance-agent-$KIND.service" 644 && units_changed=1 || true
    done

    if [ -f "/etc/letsencrypt/live/$HOST/fullchain.pem" ]; then
        install_file "$HERE/nginx/$HOST.conf" "/etc/nginx/sites-enabled/$HOST.conf" 644 && nginx_changed=1 || true
        installed_hosts+=("$HOST.conf")
    else
        echo "cert      $HOST has no certificate yet — vhost NOT installed. Once DNS points here:"
        echo "            certbot certonly --nginx --cert-name $HOST -d $HOST --deploy-hook \"systemctl reload nginx\""
        echo "          then re-run this script."
    fi
done

if [ "$units_changed" = 1 ]; then
    systemctl daemon-reload
    systemctl enable storeglance-agent-api.service storeglance-agent-gateway.service \
        uat-storeglance-agent-api.service uat-storeglance-agent-gateway.service >/dev/null
    echo "systemd   reloaded; units enabled (they start on first deploy)"
fi

if [ "$nginx_changed" = 1 ]; then
    if nginx -t 2>/tmp/storeglance-agent-nginx-test; then
        systemctl reload nginx; echo "nginx     config valid, reloaded"
    else
        cat /tmp/storeglance-agent-nginx-test >&2
        echo "nginx     INVALID — restoring previous files" >&2
        for f in "${installed_hosts[@]}"; do
            if [ -f "$BACKUP/$f" ]; then cp -a "$BACKUP/$f" /etc/nginx/sites-enabled/; else rm -f "/etc/nginx/sites-enabled/$f"; fi
        done
        nginx -t && exit 1
    fi
fi
echo "done"
