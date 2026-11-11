-- V015: Delivery outbox — at-least-once external sends (roadmap G.3/G.4).
--
-- External deliveries (cron results → Telegram/Teams) were fire-and-forget;
-- an adapter outage lost the message. Failed sends now land here and are
-- retried with exponential backoff (1m → 1h cap). After max_attempts the
-- row is parked as 'dead' (dead-letter). Replay manually with:
--   UPDATE ag_agents.delivery_outbox
--   SET status='pending', next_retry_at=NOW() WHERE delivery_id = ...;

CREATE TABLE IF NOT EXISTS ag_agents.delivery_outbox (
    delivery_id   BIGSERIAL PRIMARY KEY,
    platform      VARCHAR(40) NOT NULL,
    chat_id       TEXT NOT NULL,
    thread_id     TEXT,
    content       TEXT NOT NULL,
    status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'delivered', 'dead')),
    attempts      INT NOT NULL DEFAULT 0,
    max_attempts  INT NOT NULL DEFAULT 5,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outbox_due
    ON ag_agents.delivery_outbox (next_retry_at)
    WHERE status = 'pending';
