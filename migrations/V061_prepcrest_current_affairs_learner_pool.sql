-- ════════════════════════════════════════════════════════════════════════
-- V061 — Current affairs spends from the learner pool
-- ════════════════════════════════════════════════════════════════════════
-- V059 put every PrepCrest key that is not a live conversation in the
-- authoring pool. Current affairs does not fit that rule's spirit: the day's
-- briefs and editorials are what a learner opens the app for that morning,
-- and a day the authoring budget ran out on lessons must not also be a day
-- with no news. So the current-affairs editor (briefs) and the editorial
-- analyst spend the LEARNER key, and PrepCrest does not hold their jobs for
-- the provider's peak price (PrepCrest.API 0227 leaves brief_writer and
-- editorial_writer out of off_peak_only).
--
-- Their V060 daily budgets stay, as a guard against a runaway loop rather
-- than a rationing: raised so an ordinary news day — ~300 articles screened,
-- a handful briefed, an editorial or two — fits inside them, at peak price.
--
-- Idempotent.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

UPDATE ag_system.service_keys k
   SET llm_api_key = '__config:llm.api_key.prepcrest_prod_learner__', updated_at = now()
  FROM ag_system.applications a
 WHERE a.app_id = k.app_id
   AND a.name IN ('PrepCrest Current Affairs Editor', 'PrepCrest Editorial Analyst')
   AND k.llm_api_key = '__config:llm.api_key.prepcrest_prod_authoring__';

UPDATE ag_system.budgets b
   SET max_usd = v.usd, updated_at = now()
  FROM (VALUES ('PrepCrest Current Affairs Editor', 0.50),
               ('PrepCrest Editorial Analyst',      0.20)) AS v(name, usd)
  JOIN ag_system.applications a ON a.name = v.name
 WHERE b.scope_type = 'app' AND b.scope_id = a.app_id AND b.win = 'day'
   AND b.max_usd < v.usd;

COMMIT;
