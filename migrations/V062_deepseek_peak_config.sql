-- ════════════════════════════════════════════════════════════════════════
-- V062 — DeepSeek's peak schedule, as config an operator can see and edit
-- ════════════════════════════════════════════════════════════════════════
-- Agent.Core 8f55df3 prices DeepSeek-direct calls by time of day; the
-- schedule's defaults are in code (DeepSeek's published hours). These rows
-- make it visible beside the other llm.* settings and editable without a
-- deploy — chiefly the Chinese public holidays, which DeepSeek bills as
-- off-peak all day and publishes no list for. Empty peak_utc means "the
-- default"; empty offpeak_dates means "no holidays" (priced as peak — the
-- ledger errs high, never low). PrepCrest's matching schedule, which decides
-- when its generation jobs run, is ProviderPeak in its env file; keep the two
-- holiday lists the same.
-- ════════════════════════════════════════════════════════════════════════

BEGIN;

INSERT INTO ag_system.configs
    (config_key, config_value, description, is_secret, is_active,
     config_type, config_group, sort_order, requires_restart)
VALUES
    ('llm.deepseek.peak_utc', '01:00-04:00,06:00-10:00',
     'DeepSeek-direct peak-price windows, UTC, Mon–Fri (2x off-peak). Comma-separated HH:MM-HH:MM. Used to price the ledger (Agent.Core telemetry.deepseek_is_peak).',
     FALSE, TRUE, 'text', 'llm', 110, FALSE),
    ('llm.deepseek.offpeak_dates', '',
     'Chinese public holidays DeepSeek bills off-peak all day, as Beijing dates YYYY-MM-DD, comma-separated. Keep in step with PrepCrest ProviderPeak__OffPeakDates.',
     FALSE, TRUE, 'text', 'llm', 111, FALSE)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
