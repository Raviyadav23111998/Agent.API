# Agent tenant bootstrap

`agent_bootstrap.sql` is the **single source of truth** for what a freshly
onboarded agent tenant database contains. It is run **once per tenant** at
creation time — by MSystem's `CreateDatabaseHandler` in production and by
`scripts/dev/provision_agent_tenant.py` in dev — so both paths stay in lockstep.

It is generated from the **golden tenant** `prod_agent_tenant_2a5fe12b` and
contains:

- the full `ag_*` schema at the current migration level (V034 — includes
  `ag_api` and `ag_cred`, which the previous bootstrap was missing), and
- a **curated, credential-free, tenant-data-free platform seed**.

## What is seeded (platform defaults — same for every tenant)

| Table | Why |
|---|---|
| `ag_auth.roles`, `ag_auth.role_permissions` | RBAC catalog |
| `ag_system.applications`, `ag_system.modules` | app/module catalog (`llm_api_key_enc` is NULL) |
| `ag_system.code_types`, `ag_system.codes` | enum / lookup data |
| `ag_cred.providers` | credential **provider catalog** (field definitions only, no secrets) |
| `ag_system.credential_providers` | legacy provider catalog (back-compat) |
| `ag_system.agent_personas` | system default personas (prompts/guardrails, no secrets) |
| `ag_system.configs` | non-secret defaults only — `is_secret` rows and `llm.api_key` / `llm.base_url` / `llm.embedding_base_url` are **excluded** |

## What is NEVER seeded (tenant-private / secret)

`ag_auth.users`, `memberships`, `refresh_tokens`, `user_sessions`;
`ag_cred.connections`; `ag_system.credential_vault*`, `credential_bindings*`
and all `*_bak_v029` backup tables; all of `ag_brain.*` and `ag_memory.*`;
`ag_system.conversations`, `messages`, `transcript_logs`, `action_audit`,
`audit_log`, `checkpoints`; `ag_agents.cron_jobs/outputs`; `ag_bot.bots`;
`ag_notification.email_notifications`; `ag_api.integrations` / `operations` /
`integration_grants`; and every `is_secret = true` config.

Per-tenant service coordinates (Elastic index, Redis namespace, embeddings)
are seeded **after** bootstrap by the provisioner, not baked into this file.

## Regenerate

```bash
# on the VPS (golden tenant lives there); writes /tmp/agent_bootstrap_new.sql
scripts/dev/gen_bootstrap.sh
scripts/dev/verify_bootstrap.sh    # applies to a throwaway DB; asserts privacy gate = 0
```

Then copy the result to `agent_bootstrap.sql` here and re-register.

## Register into the masters

The production bootstrap lives in `ops.migration_scripts`
(`app_id='agent'`, `version='V004_bootstrap_no_creds'`, `script_type='bootstrap'`,
`checksum = md5(sql_content)`). `scripts/dev/register_bootstrap.sh` updates
`msystems_prod` (in place) and `msystems_uat` (insert/update) via
`pg_read_file()` so the large content loads without shell escaping.

## Rollback

`register_bootstrap.sh` backs up the prior prod content to
`/tmp/agent_bootstrap.prev.sql` on the VPS before overwriting. To revert,
restore that file into the same row's `sql_content` and recompute `checksum`.
