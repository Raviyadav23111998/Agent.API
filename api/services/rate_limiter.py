"""
Embed Rate Limiter — per-integration/session/IP rate limits (Phase 4).
═══════════════════════════════════════════════════════════════════════════
Uses Redis sliding-window counters when available; degrades gracefully to
in-memory counters (single-worker only) when Redis is down.

Three dimensions:
  - per_session_msg:  max messages per session per ROLLING HOUR (self-resetting)
  - per_ip_per_min:   max messages per client IP per minute (sliding window)
  - daily_token_cap:  max LLM tokens per integration per calendar day

per_session_msg was previously a 4-hour LIFETIME count that never reset on
disconnect, so a long or heavily-tested conversation hit the cap and stayed
locked for hours ("Message limit reached … start a new conversation"). It is now
a per-hour window: abuse is still bounded (and the per-IP/min + daily-token caps
are the real cost guards), but a genuine conversation self-heals each hour.

See EMBED_AGENT_PLATFORM_ARCHITECTURE.md §9b + Appendix D #5.
"""

import logging
import time
from typing import Dict, Tuple

logger = logging.getLogger("agent.embed.rate_limiter")

SESSION_WINDOW_S = 3600

DEFAULT_RATE_LIMITS = {
    "per_session_msg": 200,
    "per_ip_per_min": 10,
    "daily_token_cap": 100000,
}


def _session_bucket(session_id: str) -> str:
    """Hourly-bucketed key so the session counter self-resets each window."""
    return f"ag:rl:sess:{session_id}:{int(time.time() // SESSION_WINDOW_S)}"


class EmbedRateLimiter:
    """Embed session rate limiter with Redis + in-memory fallback."""

    def __init__(self):
        self._session_counts: Dict[str, int] = {}
        self._ip_windows: Dict[str, list] = {}

    def check(self, integration_id: int, session_id: str, client_ip: str,
              rate_limits: dict = None) -> Tuple[bool, str]:
        """Check all rate limits before processing a message.

        Args:
            integration_id: The integration id.
            session_id: Unique session identifier (e.g. WS id).
            client_ip: Client IP address.
            rate_limits: Override limits from integration config.

        Returns:
            (allowed, reason): True/"" if allowed, False/reason if blocked.
        """
        limits = {**DEFAULT_RATE_LIMITS, **(rate_limits or {})}

        max_session = limits.get("per_session_msg", 50)
        if max_session > 0:
            ok, reason = self._check_session(session_id, max_session)
            if not ok:
                return False, reason

        max_ip = limits.get("per_ip_per_min", 10)
        if max_ip > 0 and client_ip:
            ok, reason = self._check_ip(client_ip, max_ip)
            if not ok:
                return False, reason

        return True, ""

    def record_message(self, session_id: str, client_ip: str):
        """Record a message being processed (increment counters)."""
        bucket = _session_bucket(session_id)
        self._session_counts[bucket] = self._session_counts.get(bucket, 0) + 1

        now = time.time()
        if client_ip:
            window = self._ip_windows.setdefault(client_ip, [])
            window.append(now)

        try:
            self._redis_incr_session(session_id)
            if client_ip:
                self._redis_incr_ip(client_ip)
        except Exception:
            pass

    def record_tokens(self, integration_id: int, tokens: int):
        """Record token usage for daily cap tracking (best-effort)."""
        if tokens <= 0:
            return
        try:
            from core.redis_client import get_redis
            r = get_redis()
            if r is None:
                return
            import datetime
            date_key = datetime.date.today().isoformat()
            key = f"ag:rl:tokens:{integration_id}:{date_key}"
            r.incrby(key, tokens)
            r.expire(key, 86400 * 2)
        except Exception as e:
            logger.debug("Rate limiter token record failed (non-critical): %s", e)

    def check_daily_tokens(self, integration_id: int,
                           rate_limits: dict = None) -> Tuple[bool, str]:
        """Check if the daily token cap is exceeded (best-effort)."""
        limits = {**DEFAULT_RATE_LIMITS, **(rate_limits or {})}
        cap = limits.get("daily_token_cap", 0)
        if cap <= 0:
            return True, ""
        try:
            from core.redis_client import get_redis
            r = get_redis()
            if r is None:
                return True, ""
            import datetime
            date_key = datetime.date.today().isoformat()
            key = f"ag:rl:tokens:{integration_id}:{date_key}"
            used = int(r.get(key) or 0)
            if used >= cap:
                logger.warning("Daily token cap exceeded for integration %s: %d/%d",
                               integration_id, used, cap)
                return False, (
                    f"Daily token limit reached ({used:,}/{cap:,}). "
                    f"Please try again tomorrow."
                )
        except Exception as e:
            logger.debug("Daily token check failed (allowing): %s", e)
        return True, ""

    def cleanup_session(self, session_id: str):
        """Clean up in-memory counters when a session ends.

        Counters are hourly-bucketed (f"ag:rl:sess:{sid}:{hour}"), so drop every
        bucket for this session to avoid an unbounded in-memory dict in the
        Redis-down fallback path. (Redis keys self-expire via their TTL.)
        """
        prefix = f"ag:rl:sess:{session_id}:"
        for k in [k for k in self._session_counts if k.startswith(prefix)]:
            self._session_counts.pop(k, None)


    def _check_session(self, session_id: str, limit: int) -> Tuple[bool, str]:
        bucket = _session_bucket(session_id)
        msg = (f"Too many messages in a short time ({limit}/hour). "
               f"Please wait a little and try again.")
        try:
            from core.redis_client import get_redis
            r = get_redis()
            if r is not None:
                count = int(r.get(bucket) or 0)
                return (count < limit), ("" if count < limit else msg)
        except Exception:
            pass
        count = self._session_counts.get(bucket, 0)
        return (count < limit), ("" if count < limit else msg)

    def _check_ip(self, client_ip: str, limit: int) -> Tuple[bool, str]:
        try:
            from core.redis_client import get_redis
            r = get_redis()
            if r is not None:
                import math
                minute = math.floor(time.time() / 60)
                key = f"ag:rl:ip:{client_ip}:{minute}"
                count = int(r.get(key) or 0)
                if count >= limit:
                    return False, (
                        f"Too many messages. Please wait a moment before sending more."
                    )
                return True, ""
        except Exception:
            pass
        now = time.time()
        window = self._ip_windows.get(client_ip, [])
        cutoff = now - 60
        window = [t for t in window if t > cutoff]
        self._ip_windows[client_ip] = window
        if len(window) >= limit:
            return False, "Too many messages. Please wait a moment before sending more."
        return True, ""


    @staticmethod
    def _redis_incr_session(session_id: str):
        from core.redis_client import get_redis
        r = get_redis()
        if r is None:
            return
        key = _session_bucket(session_id)
        r.incr(key)
        r.expire(key, SESSION_WINDOW_S * 2)

    @staticmethod
    def _redis_incr_ip(client_ip: str):
        from core.redis_client import get_redis
        r = get_redis()
        if r is None:
            return
        import math
        minute = math.floor(time.time() / 60)
        key = f"ag:rl:ip:{client_ip}:{minute}"
        r.incr(key)
        r.expire(key, 120)


embed_rate_limiter = EmbedRateLimiter()
