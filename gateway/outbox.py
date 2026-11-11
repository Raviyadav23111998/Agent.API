"""
Delivery Outbox — at-least-once external sends with retry + dead-letter.
═══════════════════════════════════════════════════════════════════════

Roadmap G.3/G.4: external deliveries (cron results → Telegram/Teams) used
to be fire-and-forget — an adapter outage lost the message. Now a failed
send is persisted to ag_agents.delivery_outbox and retried with
exponential backoff; after max_attempts it is parked as 'dead' for manual
replay (UPDATE ... SET status='pending', next_retry_at=NOW()).

The gateway flushes the outbox on every cron tick. The claim is atomic
(UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED) RETURNING), so
multiple gateway instances can flush concurrently without double-sending;
rows stuck in 'processing' (a gateway died mid-flush) are reclaimed after
a 10-minute lease.
"""

import logging
from typing import Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

_BACKOFF_BASE_S = 60
_BACKOFF_CAP_S = 3600


class DeliveryOutbox:
    """PostgreSQL-backed outbox for platform messages."""

    def __init__(self, db):
        self._db = db

    def enqueue(self, platform: str, chat_id: str, content: str,
                thread_id: str = None, last_error: str = "") -> None:
        """Persist a message that could not be delivered right now."""
        try:
            self._db.execute("""
                INSERT INTO ag_agents.delivery_outbox
                    (platform, chat_id, thread_id, content, last_error)
                VALUES (%s, %s, %s, %s, %s)
            """, (platform, str(chat_id), thread_id, content, last_error[:500]))
            logger.info("[Outbox] Queued delivery: platform=%s chat=%s",
                        platform, str(chat_id)[:20])
        except Exception as e:
            logger.error("[Outbox] ENQUEUE FAILED (message lost): %s", e)

    async def flush(self, send_fn: Callable[[str, str, str, str], Awaitable[bool]],
                    limit: int = 20) -> int:
        """Attempt delivery of due rows. Returns number delivered.

        send_fn(platform, chat_id, content, thread_id) -> True on success.
        """
        rows = self._claim_due(limit)
        delivered = 0
        for row in rows:
            try:
                ok = await send_fn(row["platform"], row["chat_id"],
                                   row["content"], row.get("thread_id"))
                err = "" if ok else "adapter unavailable or send returned falsy"
            except Exception as e:
                ok, err = False, str(e)
            if ok:
                self._mark_delivered(row["delivery_id"])
                delivered += 1
            else:
                self._mark_failed(row, err)
        return delivered


    CLAIM_LEASE_MINUTES = 10

    def _claim_due(self, limit: int) -> List[Dict]:
        """Atomically claim due rows (safe under concurrent gateways).

        SKIP LOCKED makes concurrent claimers take disjoint sets; the
        status flip to 'processing' happens in the same transaction, so a
        crash between claim and send leaves the row leased, and the lease
        expiry below returns it to the pool. Falls back to the legacy
        non-transactional SELECT if execute_returning_all is unavailable
        (older TenantDB) — correct for the single-gateway deployment.
        """
        claim_sql = """
            UPDATE ag_agents.delivery_outbox
            SET status = 'processing', updated_at = NOW()
            WHERE delivery_id IN (
                SELECT delivery_id FROM ag_agents.delivery_outbox
                WHERE (status = 'pending' AND next_retry_at <= NOW())
                   OR (status = 'processing'
                       AND updated_at < NOW() - (%s || ' minutes')::interval)
                ORDER BY next_retry_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            RETURNING delivery_id, platform, chat_id, thread_id, content,
                      attempts, max_attempts
        """
        try:
            claimer = getattr(self._db, "execute_returning_all", None)
            if callable(claimer):
                return claimer(claim_sql, (self.CLAIM_LEASE_MINUTES, limit)) or []
            return self._db.fetch_all("""
                SELECT delivery_id, platform, chat_id, thread_id, content,
                       attempts, max_attempts
                FROM ag_agents.delivery_outbox
                WHERE status = 'pending' AND next_retry_at <= NOW()
                ORDER BY next_retry_at ASC
                LIMIT %s
            """, (limit,)) or []
        except Exception as e:
            logger.error("[Outbox] claim failed: %s", e)
            return []

    def _mark_delivered(self, delivery_id: int) -> None:
        try:
            self._db.execute("""
                UPDATE ag_agents.delivery_outbox
                SET status = 'delivered', delivered_at = NOW(),
                    attempts = attempts + 1
                WHERE delivery_id = %s
            """, (delivery_id,))
        except Exception as e:
            logger.error("[Outbox] mark_delivered failed: %s", e)

    def _mark_failed(self, row: Dict, error: str) -> None:
        attempts = (row.get("attempts") or 0) + 1
        max_attempts = row.get("max_attempts") or 5
        backoff = min(_BACKOFF_BASE_S * (2 ** (attempts - 1)), _BACKOFF_CAP_S)
        dead = attempts >= max_attempts
        try:
            self._db.execute("""
                UPDATE ag_agents.delivery_outbox
                SET attempts = %s,
                    last_error = %s,
                    status = %s,
                    next_retry_at = NOW() + (%s || ' seconds')::interval
                WHERE delivery_id = %s
            """, (attempts, error[:500], "dead" if dead else "pending",
                  backoff, row["delivery_id"]))
            if dead:
                logger.error(
                    "[Outbox] DEAD-LETTER after %d attempts: platform=%s "
                    "chat=%s err=%s", attempts, row["platform"],
                    str(row["chat_id"])[:20], error[:120])
        except Exception as e:
            logger.error("[Outbox] mark_failed failed: %s", e)
