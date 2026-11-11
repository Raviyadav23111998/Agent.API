-- ════════════════════════════════════════════════════════════════════════
-- MSYS_V002 — Agent app billing cycle + pilot tenant subscription
-- ════════════════════════════════════════════════════════════════════════
-- Target DB: msystems_prod
-- ADDITIVE / idempotent. Enables the 'agent' app for a pilot tenant so the
-- app-scoped resolution (MSystemRouter, AG_APP_KEY='agent') returns it.
--
-- Pilot tenant = the-ganga-convent-school (5fe3034b…6008a30d9b4a) → already
-- maps to prod_tenant_a30d9b4a (the tenant referenced throughout the design).
--
-- Without this, NO tenant is subscribed to 'agent', so the agent site shows
-- none — which is the correct default (see MULTITENANT_MASTER_PLAN.md, app scoping).
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

-- 1) A billing cycle for the agent app (required by subscriptions.billing_cycle_id).
INSERT INTO tenant_mgmt.app_billing_cycles (app_id, cycle_key, duration_months, price, discount_percent, is_active)
SELECT a.id, 'monthly', 1, 0.00, 0.00, TRUE
FROM tenant_mgmt.apps a
WHERE a.app_key = 'agent'
  AND NOT EXISTS (
      SELECT 1 FROM tenant_mgmt.app_billing_cycles bc
      WHERE bc.app_id = a.id AND bc.cycle_key = 'monthly');

-- 2) Subscribe the pilot tenant to the agent app (active for 1 year).
INSERT INTO tenant_mgmt.subscriptions
    (tenant_id, app_id, billing_cycle_id, status, current_period_start, current_period_end, auto_renew)
SELECT t.tenant_id, a.id, bc.id, 'active', NOW(), NOW() + INTERVAL '365 days', TRUE
FROM tenant_mgmt.tenants t
CROSS JOIN tenant_mgmt.apps a
JOIN tenant_mgmt.app_billing_cycles bc ON bc.app_id = a.id AND bc.cycle_key = 'monthly'
WHERE a.app_key = 'agent'
  AND t.tenant_key = 'the-ganga-convent-school'
  AND NOT EXISTS (
      SELECT 1 FROM tenant_mgmt.subscriptions s
      WHERE s.tenant_id = t.tenant_id AND s.app_id = a.id);

COMMIT;

-- Verify (manual):
--   SELECT t.tenant_key, ap.app_key, s.status
--   FROM tenant_mgmt.subscriptions s
--   JOIN tenant_mgmt.apps ap ON ap.id=s.app_id
--   JOIN tenant_mgmt.tenants t ON t.tenant_id=s.tenant_id
--   WHERE ap.app_key='agent';
