-- V021: Microsoft 365 / Teams org-app credential model.
-- Before: every user's m365 credential duplicated the ENTIRE org app
-- registration (client_id + tenant_id + client_secret). After: the app
-- registration + secret live ONCE as a system credential (admin-set); a
-- per-user credential carries only the mailbox email. The registry merges
-- the two at resolve() time (see CredentialRegistry._merge_org_app).

-- 1. Flag providers that use the org-app model.
ALTER TABLE ag_system.credential_providers
    ADD COLUMN IF NOT EXISTS org_app BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE ag_system.credential_providers SET org_app = TRUE WHERE provider_key = 'm365';

-- 2. Re-scope the m365 provider schema so the web forms know which fields are
--    ADMIN/org-level vs per-USER. (scope: "org" → admin credentials-admin;
--    scope: "user" → per-user integrations.)
UPDATE ag_system.credential_providers
SET config_schema = '{
  "fields": [
    {"key": "tenant_id", "label": "Azure AD Tenant ID", "type": "text", "required": true, "is_secret": false, "scope": "org",
     "help": "Azure Portal > Microsoft Entra ID > Overview. Set once by an admin.", "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
    {"key": "client_id", "label": "Application (Client) ID", "type": "text", "required": true, "is_secret": false, "scope": "org",
     "help": "App Registration > Overview > Application (client) ID. Set once by an admin.", "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"},
    {"key": "client_secret", "label": "Client Secret Value", "type": "password", "required": true, "is_secret": true, "scope": "org",
     "help": "App Registration > Certificates & Secrets > Client secrets > Value. Set once by an admin.", "placeholder": "Enter the client secret value (not the ID)"},
    {"key": "user_email", "label": "Your Mailbox Email", "type": "email", "required": true, "is_secret": false, "scope": "user",
     "help": "The Microsoft 365 mailbox you want the agent to access — usually your own work email.", "placeholder": "you@company.com"}
  ]
}'::jsonb
WHERE provider_key = 'm365';

-- 3. Migrate per-user m365 credentials → identity-only (email), drop the
--    duplicated app registration + secret. The org secret now comes from the
--    system credential via the resolver merge.
UPDATE ag_system.credential_vault
SET config_json = jsonb_strip_nulls(jsonb_build_object('user_email', config_json->>'user_email')),
    secret_enc = NULL
WHERE provider_key = 'm365' AND owner_type = 'user';

-- (System m365 credential keeps client_id/tenant_id/client_secret as the org
--  app registration; its user_email acts as the default mailbox for
--  system/cron contexts.)

-- 4. Fix a mis-wired Jira binding: user 1's user-binding pointed at the SYSTEM
--    migrated credential instead of their own personal credential (id 11).
UPDATE ag_system.credential_bindings
SET credential_id = 11
WHERE context_type = 'user' AND context_id = '1' AND provider_key = 'jira'
  AND EXISTS (SELECT 1 FROM ag_system.credential_vault
              WHERE credential_id = 11 AND owner_type = 'user' AND owner_id = 1
                AND provider_key = 'jira');
