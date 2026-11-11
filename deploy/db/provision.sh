#!/usr/bin/env bash
#
# Provision a standalone Storeglance Agent environment (safe to re-run):
#
#   OPENROUTER_API_KEY=sk-or-... ADMIN_EMAIL=you@example.com deploy/db/provision.sh <uat|prod>
#
#   1. role + database           storeglance_agent_<env>(_user)
#   2. schema                    migrations.list, only on an empty database
#   3. platform config rows      LLM (OpenRouter), embeddings, media paths
#   4. secrets                   /etc/storeglance/<env>/agent/.env (generated once:
#                                JWT RSA pair, Fernet key, field key, service token)
#   5. first owner account       only when the database has no users; its one-time
#                                password goes to admin-initial-password (root only)
#
# Nothing here reads or writes MSystem: the agent's own database is its control plane.

set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
ENV=${1:-}; case "$ENV" in uat|prod) ;; *) echo "usage: $0 <uat|prod>" >&2; exit 2;; esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIG="$(cd "$HERE/../../migrations" && pwd)"

DB=storeglance_agent_$ENV
ROLE=${DB}_user
if [ "$ENV" = prod ]; then HOST=ai.storeglance.com;     AGENV=Production; REDIS_DB=2; TEAMS_PORT=8135
else                       HOST=uat-ai.storeglance.com; AGENV=UAT;        REDIS_DB=3; TEAMS_PORT=8136; fi
STATE=/var/lib/storeglance-agent/$ENV
ETC=/etc/storeglance/$ENV/agent
ENVF=$ETC/.env

psql_su() { (cd /tmp && sudo -u postgres psql -X -q -v ON_ERROR_STOP=1 "$@"); }
envval() { [ -f "$ENVF" ] && sed -n "s/^$1=//p" "$ENVF" | head -1 || true; }

install -d -m 750 -o root -g sgagent "$ETC"
install -d -m 750 -o sgagent -g sgagent "$STATE/logs"

# ── 1. role + database ────────────────────────────────────────────────────
DBPW=$(envval AG_DATABASE_URL | sed -nE 's#^postgresql://[^:]+:([^@]+)@.*#\1#p')
[ -n "$DBPW" ] || DBPW=$(openssl rand -hex 24)
if [ "$(psql_su -Atc "select 1 from pg_roles where rolname='$ROLE'")" = 1 ]; then
    psql_su -c "ALTER ROLE $ROLE WITH LOGIN PASSWORD '$DBPW'"
    echo "role      $ROLE exists (password synced with $ENVF)"
else
    psql_su -c "CREATE ROLE $ROLE WITH LOGIN PASSWORD '$DBPW'"
    echo "role      $ROLE created"
fi
if [ "$(psql_su -Atc "select 1 from pg_database where datname='$DB'")" = 1 ]; then
    echo "database  $DB exists"
else
    psql_su -c "CREATE DATABASE $DB OWNER $ROLE"
    echo "database  $DB created"
fi
psql_su -d "$DB" -c "REVOKE ALL ON DATABASE $DB FROM PUBLIC; GRANT CONNECT, TEMP ON DATABASE $DB TO $ROLE"

DSN="postgresql://$ROLE:$DBPW@127.0.0.1:5432/$DB"
psql_app() { PGPASSWORD="$DBPW" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U "$ROLE" -d "$DB" "$@"; }

# ── 2. schema (only on an empty database) ─────────────────────────────────
if [ "$(psql_app -Atc "select to_regclass('ag_system.configs') is not null")" = t ]; then
    echo "schema    present — not re-applied (apply new V0xx files by hand)"
    FRESH=0
else
    FRESH=1
    grep -vE '^\s*(#|$)' "$HERE/migrations.list" | while read -r f; do
        t0=$(date +%s%3N)
        psql_app -f "$MIG/$f" >/dev/null
        # Resync every serial after each step: the bootstrap ships seed rows
        # with explicit ids, and later INSERTs would otherwise collide.
        psql_app >/dev/null <<'SQL'
DO $$ DECLARE r record; m bigint; BEGIN
  FOR r IN SELECT s.relname AS seq, n.nspname AS sch, t.relname AS tbl, a.attname AS col
           FROM pg_class s JOIN pg_depend d ON d.objid = s.oid AND d.deptype IN ('a','i')
           JOIN pg_class t ON t.oid = d.refobjid JOIN pg_namespace n ON n.oid = t.relnamespace
           JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
           WHERE s.relkind = 'S' LOOP
    EXECUTE format('SELECT coalesce(max(%I),0) FROM %I.%I', r.col, r.sch, r.tbl) INTO m;
    PERFORM setval(quote_ident(r.sch) || '.' || quote_ident(r.seq), greatest(m, 1), m > 0);
  END LOOP; END $$;
SQL
        v=$(basename "$f" .sql); ver=${v%%_*}; [ "${f#bootstrap/}" != "$f" ] && ver=V034
        psql_app -c "INSERT INTO ag_system.migration_history (version, script_name, description, applied_by, execution_ms)
                     VALUES ('$ver', '$(basename "$f")', 'storeglance provision', 'provision.sh', $(( $(date +%s%3N) - t0 )))" >/dev/null 2>&1 || true
        echo "schema    applied $f"
    done
fi

# ── 3. platform config (own DB is the control plane) ──────────────────────
# Media paths always; the LLM defaults only on a fresh database — after that the
# admin UI owns them and a re-run must never overwrite what was saved there.
psql_app >/dev/null <<SQL
INSERT INTO ag_system.configs (config_key, config_value, is_secret, is_active) VALUES
  ('media.base_path',        '$STATE/media/', false, true),
  ('media.image_base_path',  '$STATE/media/', false, true),
  ('media.doc_base_path',    '$STATE/media/Document/', false, true),
  ('media.audio_base_path',  '$STATE/media/Audio/', false, true),
  ('media.video_base_path',  '$STATE/media/Video/', false, true)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, is_active = true;
-- Infra comes from the environment file; stale DB rows would shadow it.
DELETE FROM ag_system.configs WHERE config_key ~ '^(neo4j|elasticsearch|redis|db)\.';
SQL
if [ "$FRESH" = 1 ]; then
psql_app >/dev/null <<SQL
INSERT INTO ag_system.configs (config_key, config_value, is_secret, is_active) VALUES
  ('llm.provider',           'openrouter', false, true),
  ('llm.base_url',           'https://openrouter.ai/api/v1/chat/completions', false, true),
  ('llm.model',              'deepseek/deepseek-v4-flash', false, true),
  ('llm.fallback_model',     'deepseek/deepseek-v4-flash', false, true),
  ('llm.provider_order',     'DeepInfra', false, true),
  ('llm.embedding_base_url', 'http://localhost:11434/v1', false, true)
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, is_active = true;
UPDATE ag_system.llm_profiles
   SET provider = 'openrouter',
       base_url = 'https://openrouter.ai/api/v1/chat/completions',
       model    = CASE WHEN model LIKE '%/%' THEN model ELSE 'deepseek/' || model END,
       fallback_model = CASE WHEN coalesce(fallback_model, '') = '' OR fallback_model LIKE '%/%'
                             THEN fallback_model ELSE 'deepseek/' || fallback_model END,
       -- V035 sentinel: the key is resolved from config/env (OPENROUTER_API_KEY).
       api_key  = '__config:llm.api_key__'
 WHERE provider = 'deepseek';
SQL
echo "config    LLM defaults seeded (OpenRouter) — change them in the admin UI"
fi
echo "config    media under $STATE/media"

# ── 4. secrets / environment file ─────────────────────────────────────────
# shellcheck disable=SC1091
. /etc/storeglance/neo4j.env
keep() { local v; v=$(envval "$1"); [ -n "$v" ] && echo "$v" || eval "$2"; }
rsa_priv=$(envval SECRET_PRIVATE_KEY); rsa_pub=$(envval SECRET_PUBLIC_KEY)
if [ -z "$rsa_priv" ] || [ -z "$rsa_pub" ]; then
    tmpk=$(mktemp); openssl genrsa -out "$tmpk" 2048 2>/dev/null
    rsa_priv=$(openssl pkcs8 -topk8 -nocrypt -in "$tmpk" -outform DER | base64 -w0)
    rsa_pub=$(openssl rsa -in "$tmpk" -pubout -outform DER 2>/dev/null | base64 -w0)
    shred -u "$tmpk"
fi
llm_key=${OPENROUTER_API_KEY:-$(envval OPENROUTER_API_KEY)}
[ -n "$llm_key" ] || echo "WARNING: OPENROUTER_API_KEY not provided — the agent cannot call an LLM until it is set in $ENVF" >&2

umask 027
cat > "$ENVF.new" <<EOF
# Storeglance Agent — $AGENV. Written by deploy/db/provision.sh; secrets are
# generated once and preserved on re-runs. Standalone: no AG_MSYSTEM_URL.
AG_ENVIRONMENT=$AGENV
AG_DATABASE_URL=$DSN
AG_MULTI_TENANT=0
AG_DATA_NAMESPACE=storeglance_$ENV
AG_PUBLIC_API_BASE=https://$HOST
OPENROUTER_API_KEY=$llm_key
SECRET_PRIVATE_KEY=$rsa_priv
SECRET_PUBLIC_KEY=$rsa_pub
SECRET_ISSUER=Storeglance.Agent
SECRET_AUDIENCE=Storeglance.Agent.Clients
SECRET_ENCRYPTION_KEY=$(keep SECRET_ENCRYPTION_KEY "openssl rand 32 | base64 -w0 | tr '+/' '-_'")
AG_FIELD_ENCRYPTION_KEY=$(keep AG_FIELD_ENCRYPTION_KEY "openssl rand -base64 32")
AG_SERVICE_TOKEN=$(keep AG_SERVICE_TOKEN "openssl rand -hex 24")
REDIS_URL=redis://localhost:6379/$REDIS_DB
ELASTICSEARCH_URL=http://localhost:9200
NEO4J_URI=bolt://127.0.0.1:7688
NEO4J_HTTP_URL=http://127.0.0.1:7475
NEO4J_USER=neo4j
NEO4J_PASSWORD=$NEO4J_PASSWORD
AG_TEAMS_WORKER_PORT=$TEAMS_PORT
AG_VSCODE_VSIX_DIR=/var/lib/storeglance-agent/vsix/vscode
AG_VS_VSIX_DIR=/var/lib/storeglance-agent/vsix/visualstudio
AG_DB_POOL_MIN=1
AG_DB_POOL_MAX=8
AG_LOG_DIR=$STATE/logs
EOF
umask 022
chown root:sgagent "$ENVF.new"; chmod 640 "$ENVF.new"
[ -f "$ENVF" ] && cp -a "$ENVF" "$ENVF.bak.$(date +%Y%m%d_%H%M%S)"
mv "$ENVF.new" "$ENVF"
echo "env       $ENVF written"

# ── 5. first owner account ────────────────────────────────────────────────
if [ "$(psql_app -Atc "select count(*) from ag_auth.users")" = 0 ]; then
    email=${ADMIN_EMAIL:-admin@storeglance.com}
    pw=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)
    read -r hash salt < <(PW="$pw" python3 -c '
import hmac, hashlib, os
s = os.urandom(128); h = hmac.new(s, os.environ["PW"].encode(), hashlib.sha512).hexdigest()
print(h, s.hex())')
    psql_app -c "INSERT INTO ag_auth.users (user_code, email, full_name, role_id, is_active, password_hash, salt, platform, app_id)
                 VALUES ('admin', '$email', 'Storeglance Admin', 1, true, '$hash', decode('$salt','hex'), 'web', 1)" >/dev/null
    umask 077; printf 'user: admin\nemail: %s\npassword: %s\n' "$email" "$pw" > "$ETC/admin-initial-password"; umask 022
    echo "admin     owner 'admin' <$email> created — password in $ETC/admin-initial-password (change it after first login)"
else
    echo "admin     users exist — none created"
fi
echo "done"
