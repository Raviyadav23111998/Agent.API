-- V019: transactional outbox claim support (K.2 / G hardening).
-- Adds the 'processing' lease state + updated_at so multiple gateways can
-- claim disjoint row sets with FOR UPDATE SKIP LOCKED, and a crashed
-- claimer's rows are reclaimed after the lease expires.

ALTER TABLE ag_agents.delivery_outbox
    DROP CONSTRAINT IF EXISTS delivery_outbox_status_check;

ALTER TABLE ag_agents.delivery_outbox
    ADD CONSTRAINT delivery_outbox_status_check
    CHECK (status IN ('pending', 'processing', 'delivered', 'dead'));

ALTER TABLE ag_agents.delivery_outbox
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now();
