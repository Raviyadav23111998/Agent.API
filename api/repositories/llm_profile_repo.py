"""
LLM Profile Repository — ag_system.llm_profiles / llm_usage / budgets (V035).

A profile is a COMPLETE model identity (provider, model, base_url, api_key,
params). Applications and users bind to a profile; resolution per turn is
agent-definition > request param > user > app > default. The usage ledger
records every LLM call (all surfaces) and budgets are enforced against its
window aggregates.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)

PROFILE_COLS = ("profile_id, name, provider, model, base_url, api_key, "
                "small_model, fallback_model, temperature, max_tokens, "
                "reasoning_effort, is_default, is_active, created_at, updated_at")
# Qualified for JOINs against applications/users — those tables share
# column names (name, is_active, created_at, …); unqualified selection
# raises "column reference is ambiguous" and silently killed resolution.
PROFILE_COLS_P = ", ".join(f"p.{c.strip()}" for c in PROFILE_COLS.split(","))


def window_start(win: str, now: datetime = None) -> datetime:
    """UTC window start for day|week|month (matches the reset time we show)."""
    now = now or datetime.now(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if win == "week":
        return day - timedelta(days=day.weekday())
    if win == "month":
        return day.replace(day=1)
    return day


def window_reset(win: str, now: datetime = None) -> datetime:
    start = window_start(win, now)
    if win == "week":
        return start + timedelta(days=7)
    if win == "month":
        return (start + timedelta(days=32)).replace(day=1)
    return start + timedelta(days=1)


class LLMProfileRepository:

    def __init__(self, db: TenantDB):
        self._db = db

    # ── Profiles ─────────────────────────────────────────────────────────
    def list_profiles(self, include_inactive: bool = False) -> List[Dict]:
        where = "" if include_inactive else "WHERE is_active"
        return self._db.fetch_all(
            f"SELECT {PROFILE_COLS} FROM ag_system.llm_profiles {where} "
            f"ORDER BY is_default DESC, name") or []

    def get_profile(self, profile_id: int) -> Optional[Dict]:
        return self._db.fetch_one(
            f"SELECT {PROFILE_COLS} FROM ag_system.llm_profiles "
            f"WHERE profile_id = %s AND is_active", (profile_id,))

    def get_default_profile(self) -> Optional[Dict]:
        return self._db.fetch_one(
            f"SELECT {PROFILE_COLS} FROM ag_system.llm_profiles "
            f"WHERE is_default AND is_active LIMIT 1")

    def get_profile_for_app(self, app_id: int) -> Optional[Dict]:
        return self._db.fetch_one(
            f"SELECT {PROFILE_COLS_P} FROM ag_system.llm_profiles p "
            f"JOIN ag_system.applications a ON a.llm_profile_id = p.profile_id "
            f"WHERE a.app_id = %s AND p.is_active", (app_id,))

    def get_profile_for_user(self, user_id: int) -> Optional[Dict]:
        return self._db.fetch_one(
            f"SELECT {PROFILE_COLS_P} FROM ag_system.llm_profiles p "
            f"JOIN ag_auth.users u ON u.llm_profile_id = p.profile_id "
            f"WHERE u.user_id = %s AND p.is_active", (user_id,))

    def find_profile_by_model(self, model: str) -> Optional[Dict]:
        """Request-param resolution: a model name names an ACTIVE profile
        (by profile name or exact model id) — never a free-form endpoint."""
        return self._db.fetch_one(
            f"SELECT {PROFILE_COLS} FROM ag_system.llm_profiles "
            f"WHERE is_active AND (name = %s OR model = %s) "
            f"ORDER BY is_default LIMIT 1", (model, model))

    def create_profile(self, data: Dict, created_by: int = None) -> Dict:
        row = self._db.execute_returning(f"""
            INSERT INTO ag_system.llm_profiles
                (name, provider, model, base_url, api_key, small_model,
                 fallback_model, temperature, max_tokens, reasoning_effort,
                 created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING {PROFILE_COLS}
        """, (data["name"], data["provider"], data["model"], data["base_url"],
              data.get("api_key") or "", data.get("small_model"),
              data.get("fallback_model"), data.get("temperature"),
              data.get("max_tokens"), data.get("reasoning_effort"),
              created_by))
        logger.info("llm_profile.created: id=%s name=%s model=%s",
                    row["profile_id"], data["name"], data["model"])
        return row

    def update_profile(self, profile_id: int, data: Dict) -> Optional[Dict]:
        allowed = {"name", "provider", "model", "base_url", "api_key",
                   "small_model", "fallback_model", "temperature",
                   "max_tokens", "reasoning_effort", "is_active"}
        sets, vals = [], []
        for k, v in data.items():
            if k in allowed and v is not None:
                # A masked key ("*****abc12") means "unchanged".
                if k == "api_key" and str(v).startswith("*"):
                    continue
                sets.append(f"{k} = %s")
                vals.append(v)
        if not sets:
            return self.get_profile(profile_id)
        vals.append(profile_id)
        return self._db.execute_returning(
            f"UPDATE ag_system.llm_profiles SET {', '.join(sets)}, "
            f"updated_at = now() WHERE profile_id = %s RETURNING {PROFILE_COLS}",
            tuple(vals))

    def delete_profile(self, profile_id: int) -> bool:
        """Soft-delete. The default profile is undeletable (resolution floor)."""
        row = self._db.execute_returning(
            "UPDATE ag_system.llm_profiles SET is_active = FALSE, updated_at = now() "
            "WHERE profile_id = %s AND NOT is_default RETURNING profile_id",
            (profile_id,))
        return bool(row)

    # ── Bindings ─────────────────────────────────────────────────────────
    def bind_app(self, app_id: int, profile_id: Optional[int]) -> None:
        self._db.execute(
            "UPDATE ag_system.applications SET llm_profile_id = %s, "
            "updated_at = now() WHERE app_id = %s",
            (profile_id, app_id))

    def bind_user(self, user_id: int, profile_id: Optional[int]) -> None:
        self._db.execute(
            "UPDATE ag_auth.users SET llm_profile_id = %s WHERE user_id = %s",
            (profile_id, user_id))

    # ── Usage ledger ─────────────────────────────────────────────────────
    def insert_usage_batch(self, rows: List[Dict]) -> None:
        if not rows:
            return
        args = [(r.get("user_id"), r.get("app_id"), r.get("conversation_id"),
                 r.get("run_kind") or "chat", r.get("profile_id"),
                 (r.get("model") or "")[:200], int(r.get("prompt_tokens") or 0),
                 int(r.get("completion_tokens") or 0),
                 int(r.get("cached_tokens") or 0),
                 float(r.get("cost_usd") or 0.0)) for r in rows]
        placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"] * len(args))
        flat = [v for a in args for v in a]
        self._db.execute(
            "INSERT INTO ag_system.llm_usage (user_id, app_id, conversation_id, "
            "run_kind, profile_id, model, prompt_tokens, completion_tokens, "
            f"cached_tokens, cost_usd) VALUES {placeholders}", tuple(flat))

    def window_spend(self, scope_type: str, scope_id: Optional[int],
                     win: str) -> Dict[str, float]:
        """Tokens + USD consumed by a scope in the current window."""
        start = window_start(win)
        if scope_type == "user":
            where, params = "user_id = %s AND ts >= %s", (scope_id, start)
        elif scope_type == "app":
            where, params = "app_id = %s AND ts >= %s", (scope_id, start)
        else:  # tenant
            where, params = "ts >= %s", (start,)
        row = self._db.fetch_one(
            "SELECT COALESCE(SUM(prompt_tokens + completion_tokens),0) AS tokens, "
            "COALESCE(SUM(cost_usd),0) AS usd FROM ag_system.llm_usage "
            f"WHERE {where}", params) or {}
        return {"tokens": int(row.get("tokens") or 0),
                "usd": float(row.get("usd") or 0.0)}

    def usage_summary(self, group_by: str = "user", days: int = 30) -> List[Dict]:
        """Usage dashboard aggregation. group_by: user|app|model|day."""
        col = {"user": "user_id", "app": "app_id", "model": "model",
               "day": "ts::date"}.get(group_by, "user_id")
        return self._db.fetch_all(f"""
            SELECT {col} AS grp,
                   COUNT(*) AS calls,
                   SUM(prompt_tokens) AS prompt_tokens,
                   SUM(completion_tokens) AS completion_tokens,
                   SUM(cached_tokens) AS cached_tokens,
                   ROUND(SUM(cost_usd)::numeric, 6) AS cost_usd
            FROM ag_system.llm_usage
            WHERE ts >= now() - (%s || ' days')::interval
            GROUP BY {col} ORDER BY SUM(cost_usd) DESC NULLS LAST LIMIT 200
        """, (days,)) or []

    # ── Budgets ──────────────────────────────────────────────────────────
    def list_budgets(self) -> List[Dict]:
        return self._db.fetch_all(
            "SELECT * FROM ag_system.budgets WHERE is_active "
            "ORDER BY scope_type, scope_id NULLS FIRST") or []

    def budgets_for(self, user_id: Optional[int],
                    app_id: Optional[int]) -> List[Dict]:
        """Every active budget that binds this turn (user + app + tenant)."""
        return self._db.fetch_all("""
            SELECT * FROM ag_system.budgets
            WHERE is_active AND (
                  (scope_type = 'user'   AND scope_id = %s)
               OR (scope_type = 'app'    AND scope_id = %s)
               OR (scope_type = 'tenant'))
        """, (user_id, app_id)) or []

    def upsert_budget(self, data: Dict, created_by: int = None) -> Dict:
        return self._db.execute_returning("""
            INSERT INTO ag_system.budgets
                (scope_type, scope_id, win, max_tokens, max_usd, action, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (scope_type, COALESCE(scope_id, 0), win) DO UPDATE SET
                max_tokens = EXCLUDED.max_tokens, max_usd = EXCLUDED.max_usd,
                action = EXCLUDED.action, is_active = TRUE, updated_at = now()
            RETURNING *
        """, (data["scope_type"], data.get("scope_id"), data.get("win", "day"),
              int(data.get("max_tokens") or 0), float(data.get("max_usd") or 0),
              data.get("action", "block"), created_by))

    def delete_budget(self, budget_id: int) -> bool:
        row = self._db.execute_returning(
            "UPDATE ag_system.budgets SET is_active = FALSE, updated_at = now() "
            "WHERE budget_id = %s RETURNING budget_id", (budget_id,))
        return bool(row)
