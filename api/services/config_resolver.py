"""
ConfigResolver — versioned, per-turn config resolution (redesign Stage 1, C1).
═══════════════════════════════════════════════════════════════════════════════
The keystone of the runtime redesign (AGENT_RUNTIME_REDESIGN.md §C1).

Problem it removes: config (persona, guardrails, tools, mode) was snapshotted into
a long-lived cached AgentLoop and only refreshed via bespoke invalidation hooks.
Miss a hook (or run multi-worker without Redis) and config "needs a restart".

Design: a config SCOPE (the persona + integration + application rows a session
depends on) has a monotonic VERSION = max(updated_at) across those rows. A session
records the version it was built with; each turn we compare cheaply and rebuild
only when the version advanced. Correctness is then bounded by a short TTL even
with NO Redis — the pub/sub bus becomes a pure optimization that drops the TTL to
~0 by busting the version cache the instant an admin saves.

This makes real-time config a property of the architecture, not of remembering to
fire an invalidation at every write site.
"""

from __future__ import annotations

import time
import logging
import threading

logger = logging.getLogger(__name__)

_VERSION_SQL = """
SELECT GREATEST(
  COALESCE((SELECT EXTRACT(EPOCH FROM updated_at) FROM ag_system.agent_personas
            WHERE persona_id = %(pid)s), 0),
  COALESCE((SELECT EXTRACT(EPOCH FROM updated_at) FROM ag_system.agent_personas
            WHERE app_id = %(aid)s AND is_default = TRUE AND is_active = TRUE
            ORDER BY updated_at DESC LIMIT 1), 0),
  COALESCE((SELECT EXTRACT(EPOCH FROM updated_at) FROM ag_bot.bots
            WHERE bot_id = %(iid)s), 0),
  COALESCE((SELECT EXTRACT(EPOCH FROM updated_at) FROM ag_system.applications
            WHERE app_id = %(aid)s), 0)
)::bigint AS version
"""


class ConfigResolver:
    """Resolves the config VERSION for a (tenant, app, integration, persona) scope.

    Thread-safe, in-memory TTL cache. `bust()` clears it (wired to the pub/sub
    invalidation signal) so an admin save takes effect on the very next turn.
    """

    _TTL_SECONDS = 4.0

    def __init__(self):
        self._cache: dict = {}
        self._lock = threading.Lock()

    def current_version(self, db, tenant_key: str, *, app_id=None,
                        integration_id=None, persona_id=None) -> int:
        """Monotonic config version for the scope (0 = unknown / not applicable).

        Cheap: a TTL-cached single indexed query. Returns 0 on any DB error so a
        transient blip never forces a churn of rebuilds (falls back to pub/sub +
        session TTL).
        """
        key = (tenant_key, app_id, integration_id, persona_id)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and (now - hit[1]) < self._TTL_SECONDS:
                return hit[0]
        version = self._query_version(db, app_id, integration_id, persona_id)
        with self._lock:
            self._cache[key] = (version, now)
        return version

    def bust(self):
        """Clear the version cache (called on a config-change pub/sub signal)."""
        with self._lock:
            self._cache.clear()

    @staticmethod
    def _query_version(db, app_id, integration_id, persona_id) -> int:
        try:
            row = db.fetch_one(_VERSION_SQL, {
                "pid": persona_id, "aid": app_id, "iid": integration_id,
            })
            if row:
                v = row.get("version") if isinstance(row, dict) else row[0]
                return int(v or 0)
        except Exception as e:
            logger.debug("config version query failed: %s", e)
        return 0


config_resolver = ConfigResolver()
