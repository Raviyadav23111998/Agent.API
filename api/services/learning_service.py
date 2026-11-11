"""
Learning Service — the post-turn review orchestrator (P3).

After a chat turn, the engine's collect_review_signals() says whether the
turn plausibly contained a lesson (user correction, explicit remember, long
task, a skill in play). This module owns the POLICY side hermes leaves
implicit and our platform requires:

  flag  — agent.skill_learning per tenant (skill_service.learning_enabled)
  cap   — agent.review_daily_cap reviews/tenant/day (default 20)
  cost  — reviewer runs via factory.run_agent(run_kind="review") → metered
          in ag_system.llm_usage and bounded by tenant budgets
  scope — reviews are CHAT-only by design: machine-originated turns
          (cron/bot/subagent) never signal (synthetic-identity gate in the
          engine), so the reviewer only ever learns from real users.

The review itself runs as a fire-and-forget asyncio task with the tenant
context captured — a review failure can never affect the finished turn.
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DIGEST_TAIL = 30          # messages
_DIGEST_MSG_CHARS = 400    # per message (hermes digest shape)
_INFLIGHT_TTL = 600        # s — a review can't run longer than this

# The daily cap and the per-conversation lock are cross-PROCESS state: chat
# reviews spawn in the api worker(s) while cron/bot reviews spawn in the
# gateway, so an in-memory counter would enforce cap×(processes). Redis is the
# shared source of truth (same primitive the rate limiter uses). The in-memory
# maps below are ONLY the fail-open fallback when Redis is down — single-process
# semantics, which is strictly better than crashing.
_reviews_today: Dict[Any, Any] = {}   # fallback: (tenant, yyyymmdd) -> count
_inflight: set = set()                # fallback: conversation_ids in review


def _redis():
    try:
        from core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def _daily_cap() -> int:
    try:
        from core.config import app_config
        return app_config.get_int("agent.review_daily_cap", 20)
    except Exception:
        return 20


def _cap_key(tenant_key: str) -> str:
    return f"ag:learn:reviews:{tenant_key}:{time.strftime('%Y%m%d')}"


def _under_cap(tenant_key: str) -> bool:
    r = _redis()
    if r is not None:
        try:
            return int(r.get(_cap_key(tenant_key)) or 0) < _daily_cap()
        except Exception:
            pass
    day = time.strftime("%Y%m%d")
    for k in [k for k in _reviews_today if k[1] != day]:   # drop stale days
        _reviews_today.pop(k, None)
    return _reviews_today.get((tenant_key, day), 0) < _daily_cap()


def _count(tenant_key: str):
    r = _redis()
    if r is not None:
        try:
            key = _cap_key(tenant_key)
            if r.incr(key) == 1:          # first bump today → set the TTL
                r.expire(key, 86400 * 2)
            return
        except Exception:
            pass
    key = (tenant_key, time.strftime("%Y%m%d"))
    _reviews_today[key] = _reviews_today.get(key, 0) + 1


def _inflight_acquire(conversation_id: str) -> bool:
    """Cross-process lock: True if THIS caller won the right to review this
    conversation (another worker holding it → False, skip). Redis SET NX EX;
    in-memory fallback when Redis is down."""
    r = _redis()
    if r is not None:
        try:
            return bool(r.set(f"ag:learn:inflight:{conversation_id}", "1",
                              nx=True, ex=_INFLIGHT_TTL))
        except Exception:
            pass
    if conversation_id in _inflight:
        return False
    _inflight.add(conversation_id)
    return True


def _inflight_release(conversation_id: str):
    r = _redis()
    if r is not None:
        try:
            r.delete(f"ag:learn:inflight:{conversation_id}")
            return
        except Exception:
            pass
    _inflight.discard(conversation_id)


def build_digest(history, skills_in_play) -> str:
    """Compact replay (routed-model path from hermes): recent tail, each
    message truncated — the reviewer needs the shape of the interaction,
    not every token."""
    parts = []
    for m in (history or [])[-_DIGEST_TAIL:]:
        role = m.get("role", "?")
        content = (m.get("content") or "").strip()
        if not content and m.get("tool_calls"):
            content = "(called: " + ", ".join(
                tc.get("function", {}).get("name", "?")
                for tc in m["tool_calls"]) + ")"
        if content:
            parts.append(f"[{role}] {content[:_DIGEST_MSG_CHARS]}")
    digest = "\n".join(parts)
    header = "Conversation digest (most recent last):\n"
    if skills_in_play:
        header += ("Skills that were IN PLAY this conversation "
                   f"(prefer patching these): {', '.join(skills_in_play)}\n")
    return (header + digest)[:24_000]


def maybe_review(*, review_signals=None, conversation_digest=None,
                 agent=None, cli, db, conversation_id: str,
                 user_id=None, app_id=None) -> bool:
    """Post-turn learning hook.  Returns True when a review task was spawned.

    Accepts EITHER pre-collected data (from RunResult — the factory path)
    or an ``agent`` object (from chat_service's direct AgentLoop).  The
    host layer decides; the learning service never reaches into the engine.
    """
    try:
        from api.services.skill_service import learning_enabled, attach_skills
        if not learning_enabled():
            return False
        store = attach_skills(cli, db)
        if store is None:
            return False

        # ── Resolve signals: prefer pre-collected, fall back to agent ──
        if review_signals is None and agent is not None:
            review_signals = agent.collect_review_signals()
        if review_signals is None:
            return False

        # Effectiveness: a correction in a conversation where skills were in
        # play counts against those skills — data for the curator.
        if review_signals.get("correction") and review_signals.get("skills_in_play"):
            store.record_correction_after_use(review_signals["skills_in_play"])

        if not review_signals.get("should_review"):
            return False

        try:
            from core.tenant_context import current_tenant
            tenant_ctx = current_tenant()
            tenant_key = getattr(tenant_ctx, "tenant_key", "") or ""
        except Exception:
            tenant_ctx, tenant_key = None, ""
        if not _under_cap(tenant_key):
            logger.info("learning: daily review cap reached for %s", tenant_key)
            return False

        # Cross-process lock LAST (so we don't hold it when we'd bail anyway):
        # if another worker is already reviewing this conversation, skip.
        if not _inflight_acquire(conversation_id):
            return False

        # ── Resolve digest: prefer pre-collected, fall back to agent ──
        if not conversation_digest and agent is not None:
            conversation_digest = build_digest(
                agent.conversation_history,
                review_signals.get("skills_in_play") or [])
        if not conversation_digest:
            conversation_digest = "(No conversation data available)"

        _count(tenant_key)

        async def _run():
            from core.tenant_context import set_tenant_context, reset_tenant_context
            token = set_tenant_context(tenant_ctx) if tenant_ctx is not None else None
            try:
                from agents.registry import AgentRegistry
                from agents.factory import AgentFactory, resolve_agent_definition
                registry = AgentRegistry(db)
                definition = resolve_agent_definition(registry, "reviewer")
                factory = AgentFactory(cli, registry)
                run_result = await factory.run_agent(
                    definition, task_prompt=conversation_digest, timeout=180,
                    app_id=app_id, run_kind="review")
                logger.info("learning.review conv=%s → %s",
                            (conversation_id or "")[:8],
                            (run_result.output or "")[:160])
            except TypeError:
                logger.debug("learning: engine lacks RunResult — skipped")
            except Exception as e:
                logger.warning("learning.review failed: %s", e)
            finally:
                _inflight_release(conversation_id)
                if token is not None:
                    try:
                        reset_tenant_context(token)
                    except Exception:
                        pass

        asyncio.create_task(_run())
        return True
    except Exception:
        logger.debug("learning.maybe_review failed (ignored)", exc_info=True)
        return False


def build_curator_briefing(skills: list) -> str:
    """Turn the raw skill rows into the curator's data briefing: the index
    plus the effectiveness signals that tell it what to fix first. This is
    the payload the plan's §5.2 promised — the curator works from data, not
    vibes."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def _age_days(ts):
        if not ts:
            return None
        try:
            return max(0, (now - ts).days)
        except Exception:
            return None

    lines, flagged, tag_groups = [], [], {}
    for s in skills:
        name = s.get("name")
        uc = s.get("use_count") or 0
        cau = s.get("correction_after_use") or 0
        last = _age_days(s.get("last_used_at"))
        created = _age_days(s.get("created_at"))
        tags = s.get("tags") or []
        protected = s.get("pinned") or s.get("origin") == "bundled"
        note = []
        if cau >= 2 or (uc and cau and cau / uc >= 0.5):
            note.append("HIGH-CORRECTION")
        if uc == 0 and (created is None or created >= 30):
            note.append("UNUSED")
        if protected:
            note.append("protected")
        if note:
            flagged.append(name)
        lines.append(
            f"- {name} [{s.get('scope_type', 'tenant')}] "
            f"use={uc} corrections={cau} "
            f"last_used={'never' if last is None else f'{last}d ago'} "
            f"tags={','.join(tags) or '-'}"
            + (f"  <<{' '.join(note)}>>" if note else "")
            + f"\n    desc: {s.get('description', '')}")
        for t in tags:
            tag_groups.setdefault(t, []).append(name)

    overlaps = {t: n for t, n in tag_groups.items() if len(n) > 1}
    briefing = (
        "SKILL LIBRARY BRIEFING (act on the flags — see your mission order).\n"
        f"{len(skills)} active skills.\n\n" + "\n".join(lines))
    if overlaps:
        briefing += "\n\nPOSSIBLE OVERLAP (share a tag — check for merge):\n" + \
            "\n".join(f"- {t}: {', '.join(n)}" for t, n in overlaps.items())
    if flagged:
        briefing += ("\n\nLook at these FIRST: " + ", ".join(flagged))
    return briefing[:24_000]


async def run_curator(*, cli, db, app_id=None, min_skills: int = 2) -> str:
    """Weekly library maintenance (P4). Awaited by the cron runner under the
    already-bound tenant context. Same governance as the reviewer: gated by
    the tenant flag, metered as run_kind='review', bounded by tenant budgets.
    Returns a one-line outcome for the cron log."""
    from api.services.skill_service import learning_enabled, attach_skills
    if not learning_enabled():
        return "Curator skipped (skill_learning off)."
    store = attach_skills(cli, db)
    if store is None:
        return "Curator skipped (no store)."
    # Independent entry point (fires before the cron path's attach_scope), so
    # it must bind the usage scope itself — otherwise the factory finds no
    # sink and the curator runs UNMETERED and UNBUDGETED. The design requires
    # it be governed exactly like the reviewer (run_kind='review' + budgets).
    try:
        from api.services.llm_scope import attach_scope
        attach_scope(cli)
    except Exception:
        logger.debug("curator: attach_scope skipped", exc_info=True)
    from api.repositories.skill_repo import SkillRepository
    skills = SkillRepository(db).list_all(include_inactive=False)
    if len(skills) < min_skills:
        return f"Curator: only {len(skills)} skill(s) — nothing to curate."
    briefing = build_curator_briefing(skills)
    from agents.registry import AgentRegistry
    from agents.factory import AgentFactory, resolve_agent_definition
    registry = AgentRegistry(db)
    definition = resolve_agent_definition(registry, "curator")
    if definition is None:
        return "Curator: no definition."
    factory = AgentFactory(cli, registry)
    run_result = await factory.run_agent(
        definition, task_prompt=briefing, timeout=300,
        app_id=app_id, run_kind="review")
    out = (getattr(run_result, "output", None) or "")[:200]
    logger.info("learning.curator: %s active skills → %s", len(skills), out)
    return out or "Curator ran."


_LEARN_TEMPLATE = """The user invoked /learn — turn what they describe into ONE reusable skill.

Source material: {source}

Steps:
1. Gather the named sources with the tools you already have (read files,
   fetch URLs, or use this conversation's history for "what we just did").
2. Author a single skill via skill_manage action=create:
   - name: lowercase-hyphenated, CLASS-level (how to do this KIND of task).
   - description: one line ≤100 chars — it becomes the index entry.
   - body: goal, when to use, steps, pitfalls. Concise, no filler, no
     invented commands — only tools/commands that actually exist here.
3. If substantial reference material remains, add ONE support file via
   skill_manage action=write_file (references/<topic>.md), condensed for
   the task — never a full mirror of upstream docs.
4. Reply with one line: the skill name and what it now covers."""


def build_learn_prompt(source: str) -> str:
    """/learn <anything> — standards-guided skill authoring (hermes /learn
    pattern) executed by the live conversation agent with its own tools."""
    src = source.strip() or ("what we did in this conversation so far "
                             "(use the conversation history)")
    return _LEARN_TEMPLATE.format(source=src)
