"""
LLM Scope Service — per-app/per-user model resolution + usage metering +
Claude-style budgets. The single place every execution surface (chat, bots,
crons, sub-agents, embed) goes through to answer three questions:

  1. WHICH model identity runs this turn?   → resolve_profile()
  2. WHERE does its spend get recorded?     → make_usage_sink() (ledger)
  3. MAY it (continue to) run?              → pre_turn_check() / make_budget_check()

Resolution order (most specific wins):
  agent-definition profile > request model param > user profile > app profile
  > tenant default profile > legacy global llm.* config (pre-V035 fallback).

A service key may then replace ONE field of whatever was resolved — api_key —
via with_credential() (V058). It is deliberately not a fifth scope: a scope
would bring its own model, and the point of a per-key credential is that two
deployments of one product spend on different provider keys while running
the same models.

Metering is fire-and-forget: a bounded queue drained by one daemon thread,
batched INSERTs — a ledger outage can never fail a turn. Budget reads are
cached ~20s per scope; enforcement is pre-turn (429 + reset time) and
mid-turn via the engine's budget_check hook (graceful wrap-up).
"""
import hashlib
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from api.repositories.llm_profile_repo import (LLMProfileRepository,
                                               window_reset)

logger = logging.getLogger(__name__)


def numeric_user_id(user_id) -> Optional[int]:
    """'user_5' / 5 / '5' → 5; agents/crons/embed visitors → None."""
    s = str(user_id or "")
    if s.startswith("user_"):
        s = s[5:]
    return int(s) if s.isdigit() else None


def credential_ref(api_key: str) -> str:
    """A short, non-reversible handle for a credential — what the client
    cache and the logs use instead of the key."""
    return hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:12]


def with_credential(profile: Optional[Dict], api_key: Optional[str]) -> Optional[Dict]:
    """The profile as resolved, but spending on `api_key`.

    Pure. Returns the SAME object when there is nothing to do (no override,
    or the override equals the profile's own key), so the cached client for
    the plain profile is reused and byte-identical behaviour is preserved
    for every caller that never sets a credential.

    With an override, a COPY is returned carrying the new api_key and a
    credential_ref that get_profile_client folds into its cache key — two
    keys on one profile are two clients, and neither evicts the other.

    A missing profile (pre-V035 tenant) still gets a minimal one: provider,
    model and URL then come from the legacy llm.* config inside
    create_llm_client, exactly as the legacy client's would."""
    if not api_key:
        return profile
    if profile and (profile.get("api_key") or "") == api_key:
        return profile
    out = dict(profile or {})
    out["api_key"] = api_key
    out["credential_ref"] = credential_ref(api_key)
    return out


_LEDGER_QUEUE_MAX = 10_000
_LEDGER_FLUSH_S = 5.0
_LEDGER_BATCH_MAX = 200
_BUDGET_CACHE_TTL_S = 20.0


class LLMScopeService:
    """One instance per process (holds the ledger writer thread)."""

    def __init__(self, db):
        self._db = db
        self._repo = LLMProfileRepository(db)
        self._queue: "queue.Queue[Dict]" = queue.Queue(maxsize=_LEDGER_QUEUE_MAX)
        self._budget_cache: Dict[Any, Any] = {}
        self._budget_lock = threading.Lock()
        self._writer = threading.Thread(
            target=self._drain_forever, name="llm-usage-ledger", daemon=True)
        self._writer.start()

    # ── 1. Profile resolution ────────────────────────────────────────────
    def resolve_profile(self, user_id=None, app_id: int = None,
                        requested_model: str = None) -> Optional[Dict]:
        """Resolve the model profile for a turn. None = pre-V035 tenant
        (caller falls back to the shared legacy client). user_id may be a
        raw context id ('user_5') — normalized here."""
        user_id = numeric_user_id(user_id)
        # Each step is independently fail-soft: a broken step must demote to
        # the NEXT step, not abort the whole chain (a failing user-JOIN was
        # silently disabling the default profile for every chat turn). Only
        # a failing DEFAULT lookup means "pre-V035" → None → legacy client.
        for step, fn in (
                ("request", lambda: (self._repo.find_profile_by_model(
                    requested_model.strip()) if requested_model else None)),
                ("user", lambda: (self._repo.get_profile_for_user(user_id)
                                  if user_id else None)),
                ("app", lambda: (self._repo.get_profile_for_app(app_id)
                                 if app_id else None))):
            try:
                prof = fn()
                if prof:
                    return prof
                if step == "request" and requested_model:
                    logger.info("llm_scope: requested model %r matches no "
                                "active profile — falling through",
                                requested_model)
            except Exception as e:
                logger.warning("llm_scope: %s-scope resolution failed (%s) "
                               "— trying next scope", step, e)
        try:
            return self._repo.get_default_profile()
        except Exception as e:
            logger.debug("llm_scope: profile resolution unavailable (%s)", e)
            return None

    def client_for(self, profile: Optional[Dict], legacy_client, stream=True):
        """Cached client for the profile; legacy shared client when None or
        when the profile IS the config-mirroring default (identical identity —
        reusing the shared client preserves its warm provider prefix)."""
        if not profile:
            return legacy_client
        try:
            from client.cli import get_profile_client
            return get_profile_client(profile, stream=stream)
        except Exception as e:
            logger.warning("llm_scope: profile client failed (%s) — legacy", e)
            return legacy_client

    # ── 2. Usage metering ────────────────────────────────────────────────
    def make_usage_sink(self, user_id=None, app_id: int = None,
                        run_kind: str = "chat", profile_id=None):
        """Sink injected into AgentLoop — called with every LLM call's real
        usage (engine guarantees best-effort semantics).

        user_id may arrive raw ('user_5', 'cron_user', 'bot_x', 42) — it is
        normalized here to a platform user id or None, so a non-numeric id
        can never poison the INTEGER ledger column (one bad row would fail
        the whole batched INSERT).

        MULTI-TENANT: the sink runs in request context, the writer thread
        does not — so the bound TenantContext is captured HERE and re-bound
        around the batched insert, or a TenantDBProxy would route another
        tenant's (or no) database. Same detached-work class as the Teams fix.
        """
        user_id = numeric_user_id(user_id)
        try:
            from core.tenant_context import current_tenant
            tenant_ctx = current_tenant()
        except Exception:
            tenant_ctx = None

        def sink(rec: Dict):
            row = {**rec, "user_id": user_id, "app_id": app_id,
                   "run_kind": run_kind, "profile_id": profile_id,
                   "_tenant_ctx": tenant_ctx}
            try:
                self._queue.put_nowait(row)
            except queue.Full:
                logger.warning("llm_scope: ledger queue full — dropping row")
        return sink

    def _flush_batch(self, batch: List[Dict]):
        """Insert rows grouped by their captured tenant context."""
        groups: Dict[Any, List[Dict]] = {}
        for row in batch:
            groups.setdefault(id(row.get("_tenant_ctx")) if row.get("_tenant_ctx")
                              else None, []).append(row)
        from core.tenant_context import set_tenant_context, reset_tenant_context
        for rows in groups.values():
            ctx = rows[0].get("_tenant_ctx")
            token = None
            try:
                if ctx is not None:
                    token = set_tenant_context(ctx)
                clean = [{k: v for k, v in r.items() if k != "_tenant_ctx"}
                         for r in rows]
                try:
                    self._repo.insert_usage_batch(clean)
                except Exception as e:
                    # A multi-VALUES insert is all-or-nothing: salvage the
                    # batch row-by-row so one malformed row can't erase up
                    # to _LEDGER_BATCH_MAX good ones.
                    logger.warning("llm_scope: batch flush failed (%d rows) "
                                   "— retrying per-row: %s", len(clean), e)
                    dropped = 0
                    for r in clean:
                        try:
                            self._repo.insert_usage_batch([r])
                        except Exception:
                            dropped += 1
                    if dropped:
                        logger.error("llm_scope: dropped %d unwritable "
                                     "ledger rows", dropped)
            except Exception as e:
                logger.warning("llm_scope: ledger flush failed (%d rows): %s",
                               len(rows), e)
            finally:
                if token is not None:
                    try:
                        reset_tenant_context(token)
                    except Exception:
                        pass

    def _drain_forever(self):
        batch: List[Dict] = []
        last_flush = time.monotonic()
        while True:
            timeout = max(0.2, _LEDGER_FLUSH_S - (time.monotonic() - last_flush))
            try:
                batch.append(self._queue.get(timeout=timeout))
                while len(batch) < _LEDGER_BATCH_MAX:
                    batch.append(self._queue.get_nowait())
            except queue.Empty:
                pass
            if batch and (len(batch) >= _LEDGER_BATCH_MAX
                          or time.monotonic() - last_flush >= _LEDGER_FLUSH_S):
                self._flush_batch(batch)
                batch = []
                last_flush = time.monotonic()

    # ── 3. Budgets ───────────────────────────────────────────────────────
    def _spend_cached(self, scope_type: str, scope_id, win: str) -> Dict:
        try:
            from core.tenant_context import current_tenant_id
            tenant = current_tenant_id()
        except Exception:
            tenant = ""
        key = (tenant, scope_type, scope_id, win)
        now = time.monotonic()
        with self._budget_lock:
            hit = self._budget_cache.get(key)
            if hit and now - hit[0] < _BUDGET_CACHE_TTL_S:
                return hit[1]
        spend = self._repo.window_spend(scope_type, scope_id, win)
        with self._budget_lock:
            self._budget_cache[key] = (now, spend)
        return spend

    def check_budgets(self, user_id=None,
                      app_id: int = None) -> Optional[str]:
        """Return a human message if any blocking budget is exhausted,
        else None. Most specific scope reported first."""
        user_id = numeric_user_id(user_id)
        try:
            budgets = self._repo.budgets_for(user_id, app_id)
        except Exception as e:
            logger.debug("llm_scope: budgets unavailable (%s)", e)
            return None
        order = {"user": 0, "app": 1, "tenant": 2}
        for b in sorted(budgets, key=lambda b: order.get(b["scope_type"], 9)):
            scope_id = (user_id if b["scope_type"] == "user"
                        else app_id if b["scope_type"] == "app" else None)
            spend = self._spend_cached(b["scope_type"], scope_id, b["win"])
            over_tokens = (int(b.get("max_tokens") or 0) > 0
                           and spend["tokens"] >= int(b["max_tokens"]))
            over_usd = (float(b.get("max_usd") or 0) > 0
                        and spend["usd"] >= float(b["max_usd"]))
            if not (over_tokens or over_usd):
                continue
            reset = window_reset(b["win"]).strftime("%Y-%m-%d %H:%M UTC")
            scope_word = {"user": "your", "app": "this application's",
                          "tenant": "the organization's"}[b["scope_type"]]
            if over_tokens:
                detail = (f"{spend['tokens']:,}/{int(b['max_tokens']):,} tokens")
            else:
                detail = f"${spend['usd']:.2f}/${float(b['max_usd']):.2f}"
            win_word = {"day": "daily", "week": "weekly",
                        "month": "monthly"}.get(b["win"], b["win"])
            msg = (f"You've reached {scope_word} {win_word} usage limit "
                   f"({detail}). Resets at {reset}.")
            if b.get("action") == "warn":
                logger.warning("llm_scope: budget WARN (not blocking): %s", msg)
                continue
            return msg
        return None

    def make_budget_check(self, user_id=None, app_id: int = None):
        """Mid-turn probe for AgentLoop (engine calls it between iterations)."""
        user_id = numeric_user_id(user_id)
        def check() -> Optional[str]:
            return self.check_budgets(user_id=user_id, app_id=app_id)
        return check


# Process-wide instance, created lazily with the API's DB handle.
_scope_service: Optional[LLMScopeService] = None
_scope_lock = threading.Lock()


def attach_scope(cli, db=None) -> Optional[LLMScopeService]:
    """THE way a surface binds model governance to an AgentCLI.

    Idempotently attaches the process scope service as ``cli.llm_scope`` so
    everything spawned through that CLI (factory agents, sub-agents, tools)
    inherits profile resolution, metering, and budgets — and returns the
    service for the caller's own sink/gate wiring. Never raises: a surface
    must degrade to the legacy client, not fail the turn.
    """
    try:
        svc = get_scope_service(
            db if db is not None else getattr(cli, "tenant_db", None))
        if getattr(cli, "llm_scope", None) is None:
            cli.llm_scope = svc
        return svc
    except Exception:
        logger.debug("llm_scope: attach failed", exc_info=True)
        return None


def get_scope_service(db) -> LLMScopeService:
    global _scope_service
    if _scope_service is None:
        with _scope_lock:
            if _scope_service is None:
                _scope_service = LLMScopeService(db)
    # First caller may race startup with db=None (e.g. a bot turn before the
    # proxy is attached) — a None-bound singleton would disable metering for
    # the process lifetime. Adopt the first real handle that shows up.
    if db is not None and _scope_service._db is None:
        with _scope_lock:
            if _scope_service._db is None:
                _scope_service._db = db
                _scope_service._repo = LLMProfileRepository(db)
    return _scope_service
