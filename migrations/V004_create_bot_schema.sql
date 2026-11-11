-- ═══════════════════════════════════════════════════════════════════════
-- V004: Chatbot Platform Schema (ag_bot)
-- ═══════════════════════════════════════════════════════════════════════
-- Adds embeddable chatbot support with shared knowledge architecture.
-- Knowledge lives in ag_brain.documents (full Brain power).
-- Bots link to knowledge via bot_knowledge_links (many-to-many).
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

-- ── 1. Enhance existing knowledge: add tags to ag_brain.documents ────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ag_brain' AND table_name = 'documents' AND column_name = 'tags'
    ) THEN
        ALTER TABLE ag_brain.documents ADD COLUMN tags TEXT[] DEFAULT '{}';
        CREATE INDEX idx_docs_tags ON ag_brain.documents USING GIN(tags);
        RAISE NOTICE 'Added tags column to ag_brain.documents';
    END IF;
END $$;


-- ── 2. Create ag_bot schema ──────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS ag_bot;


-- ── 3. ag_bot.bots — Bot definitions ─────────────────────────────────

CREATE TABLE IF NOT EXISTS ag_bot.bots (
    bot_id          SERIAL PRIMARY KEY,
    bot_uuid        UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            VARCHAR(200) NOT NULL,
    description     TEXT DEFAULT '',
    api_token       VARCHAR(64) NOT NULL UNIQUE,
    allowed_domains TEXT[] DEFAULT '{"*"}',
    system_prompt   TEXT NOT NULL DEFAULT 'You are a helpful assistant.',
    welcome_message TEXT DEFAULT 'Hi! How can I help you today?',
    model           VARCHAR(100),  -- NULL = use global LLM
    theme_color     VARCHAR(7) DEFAULT '#6D28D9',
    max_context_docs INT DEFAULT 5,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE TRIGGER trg_bots_updated_at
    BEFORE UPDATE ON ag_bot.bots
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


-- ── 4. ag_bot.bot_rules — URL-based behavior rules ──────────────────

CREATE TABLE IF NOT EXISTS ag_bot.bot_rules (
    rule_id     SERIAL PRIMARY KEY,
    bot_id      INT NOT NULL REFERENCES ag_bot.bots(bot_id) ON DELETE CASCADE,
    rule_type   VARCHAR(50) NOT NULL DEFAULT 'url_contains',
    pattern     VARCHAR(500) NOT NULL,
    instruction TEXT NOT NULL,
    priority    INT NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_bot_rules_bot ON ag_bot.bot_rules(bot_id, is_active, priority DESC);

ALTER TABLE ag_bot.bot_rules ADD CONSTRAINT chk_rule_type
    CHECK (rule_type IN ('url_contains', 'url_exact', 'url_regex', 'fallback'));


-- ── 5. ag_bot.bot_knowledge_links — Many-to-many: Bot ↔ Knowledge ───

CREATE TABLE IF NOT EXISTS ag_bot.bot_knowledge_links (
    link_id     SERIAL PRIMARY KEY,
    bot_id      INT NOT NULL REFERENCES ag_bot.bots(bot_id) ON DELETE CASCADE,
    doc_id      BIGINT NOT NULL REFERENCES ag_brain.documents(doc_id) ON DELETE CASCADE,
    url_scope   VARCHAR(500),  -- NULL = always available
    priority    INT NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    UNIQUE(bot_id, doc_id)
);

CREATE INDEX idx_bot_knowledge_bot ON ag_bot.bot_knowledge_links(bot_id, is_active);


-- ── 6. ag_bot.bot_conversations — Chat sessions ─────────────────────

CREATE TABLE IF NOT EXISTS ag_bot.bot_conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_id          INT NOT NULL REFERENCES ag_bot.bots(bot_id) ON DELETE CASCADE,
    session_id      VARCHAR(100) NOT NULL,
    page_url        TEXT,
    visitor_name    VARCHAR(200),
    visitor_email   VARCHAR(200),
    message_count   INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_bot_conv_session ON ag_bot.bot_conversations(bot_id, session_id);
CREATE INDEX idx_bot_conv_updated ON ag_bot.bot_conversations(bot_id, updated_at DESC);

CREATE TRIGGER trg_bot_conv_updated_at
    BEFORE UPDATE ON ag_bot.bot_conversations
    FOR EACH ROW EXECUTE FUNCTION ag_common.set_updated_at();


-- ── 7. ag_bot.bot_messages — Messages ────────────────────────────────

CREATE TABLE IF NOT EXISTS ag_bot.bot_messages (
    message_id      BIGSERIAL PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES ag_bot.bot_conversations(conversation_id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    token_count     INT DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX idx_bot_msg_conv ON ag_bot.bot_messages(conversation_id, created_at ASC);

ALTER TABLE ag_bot.bot_messages ADD CONSTRAINT chk_bot_msg_role
    CHECK (role IN ('user', 'assistant', 'system'));


-- ═══════════════════════════════════════════════════════════════════════
-- SEED DATA — Dummy bot + sample knowledge for SMSystem UAT
-- ═══════════════════════════════════════════════════════════════════════

-- Create the demo bot
INSERT INTO ag_bot.bots (name, description, api_token, allowed_domains, system_prompt, welcome_message, theme_color)
VALUES (
    'SMSystem Support',
    'Customer support chatbot for SMSystem UAT application',
    'ag_bot_smsystem_uat_demo_token_2026',
    '{"localhost", "smsystem-uat.storeglance.com", "*"}',
    'You are the SMSystem Support Assistant, a helpful and professional chatbot for the SMSystem application by Storeglance.

Your responsibilities:
- Answer questions about SMSystem features, pricing, and capabilities
- Help users troubleshoot common issues
- Guide users through the application
- Be polite, concise, and accurate
- If you don''t know something, say so honestly and suggest contacting support@storeglance.com

Important rules:
- Never share internal technical details or source code
- Always respond in the same language the user writes in
- Keep responses under 500 words unless the user asks for detail
- Use markdown formatting for better readability',
    'Hi there! 👋 I''m the SMSystem Support Assistant. How can I help you today?',
    '#6D28D9'
)
ON CONFLICT (api_token) DO NOTHING;

-- Seed sample knowledge documents into ag_brain.documents
INSERT INTO ag_brain.documents (source_path, doc_type, title, content, content_hash, token_count, status, owner_id, tags)
VALUES
(
    'bot://smsystem/pricing',
    'faq',
    'SMSystem Pricing Plans',
    'SMSystem Pricing Plans:

1. **Starter Plan** - $29/month
   - Up to 5 users
   - Basic fleet tracking
   - Email support
   - 1 GB storage

2. **Professional Plan** - $79/month
   - Up to 25 users
   - Advanced fleet management
   - GPS real-time tracking
   - Priority email & chat support
   - 10 GB storage
   - API access

3. **Enterprise Plan** - Custom pricing
   - Unlimited users
   - Full fleet management suite
   - Custom integrations
   - Dedicated account manager
   - 24/7 phone support
   - Unlimited storage
   - SLA guarantee

All plans include a 14-day free trial. No credit card required.
Contact sales@storeglance.com for enterprise pricing.',
    md5('smsystem-pricing-v1'),
    120,
    'indexed',
    '__tenant__',
    '{"pricing", "sales", "support"}'
),
(
    'bot://smsystem/features',
    'document',
    'SMSystem Product Features',
    'SMSystem Product Features:

**Fleet Management**
- Real-time GPS vehicle tracking
- Route optimization and planning
- Driver assignment and scheduling
- Fuel consumption monitoring
- Maintenance scheduling and alerts

**Logistics & Dispatch**
- Automated dispatch system
- Order management
- Delivery tracking with ETA
- Proof of delivery (photo + signature)
- Customer notification system

**Reporting & Analytics**
- Custom dashboard builder
- Fleet utilization reports
- Cost analysis
- Driver performance scorecards
- Compliance reporting

**Integrations**
- REST API for custom integrations
- QuickBooks / Xero accounting sync
- Google Maps / Mapbox integration
- Slack / Teams notifications
- Zapier connector

**Security**
- Role-based access control (RBAC)
- SSO with SAML 2.0 / OAuth
- Data encryption at rest and in transit
- Audit logs
- GDPR compliant',
    md5('smsystem-features-v1'),
    150,
    'indexed',
    '__tenant__',
    '{"product", "features", "support"}'
),
(
    'bot://smsystem/troubleshooting',
    'faq',
    'SMSystem Troubleshooting Guide',
    'Common Issues and Solutions:

**Q: I can''t log in to my account**
A: Try these steps:
1. Clear your browser cache and cookies
2. Make sure you''re using the correct email address
3. Click "Forgot Password" to reset your password
4. If using SSO, contact your IT admin
5. Still stuck? Email support@storeglance.com

**Q: GPS tracking is not updating**
A: Check the following:
1. Ensure the GPS device has power and cellular signal
2. Verify the device is registered in Settings > Devices
3. Check if the device firmware is up to date
4. Allow up to 5 minutes for initial position fix
5. Contact support if the issue persists

**Q: Reports are showing incorrect data**
A: This is usually caused by:
1. Incorrect date/time zone settings (Settings > Company > Timezone)
2. Vehicles not assigned to the correct fleet group
3. Data sync delay — wait 15 minutes and refresh
4. If data is still wrong, export the raw data and email support

**Q: How do I add a new user?**
A: Go to Settings > Users > Add User. Fill in name, email, and role. The user will receive an invitation email.',
    md5('smsystem-troubleshooting-v1'),
    200,
    'indexed',
    '__tenant__',
    '{"support", "troubleshooting", "faq"}'
)
ON CONFLICT (source_path) DO NOTHING;

-- Link knowledge to the demo bot
DO $$
DECLARE
    v_bot_id INT;
    v_doc_id BIGINT;
BEGIN
    SELECT bot_id INTO v_bot_id FROM ag_bot.bots WHERE api_token = 'ag_bot_smsystem_uat_demo_token_2026';
    IF v_bot_id IS NULL THEN RETURN; END IF;

    -- Link pricing doc (scoped to /pricing pages)
    SELECT doc_id INTO v_doc_id FROM ag_brain.documents WHERE source_path = 'bot://smsystem/pricing';
    IF v_doc_id IS NOT NULL THEN
        INSERT INTO ag_bot.bot_knowledge_links (bot_id, doc_id, url_scope, priority)
        VALUES (v_bot_id, v_doc_id, '/pricing', 10)
        ON CONFLICT (bot_id, doc_id) DO NOTHING;
    END IF;

    -- Link features doc (always available)
    SELECT doc_id INTO v_doc_id FROM ag_brain.documents WHERE source_path = 'bot://smsystem/features';
    IF v_doc_id IS NOT NULL THEN
        INSERT INTO ag_bot.bot_knowledge_links (bot_id, doc_id, url_scope, priority)
        VALUES (v_bot_id, v_doc_id, NULL, 5)
        ON CONFLICT (bot_id, doc_id) DO NOTHING;
    END IF;

    -- Link troubleshooting doc (always available)
    SELECT doc_id INTO v_doc_id FROM ag_brain.documents WHERE source_path = 'bot://smsystem/troubleshooting';
    IF v_doc_id IS NOT NULL THEN
        INSERT INTO ag_bot.bot_knowledge_links (bot_id, doc_id, url_scope, priority)
        VALUES (v_bot_id, v_doc_id, NULL, 5)
        ON CONFLICT (bot_id, doc_id) DO NOTHING;
    END IF;

    RAISE NOTICE 'Linked knowledge to bot %', v_bot_id;
END $$;

-- Seed URL-based rules for the demo bot
DO $$
DECLARE
    v_bot_id INT;
BEGIN
    SELECT bot_id INTO v_bot_id FROM ag_bot.bots WHERE api_token = 'ag_bot_smsystem_uat_demo_token_2026';
    IF v_bot_id IS NULL THEN RETURN; END IF;

    INSERT INTO ag_bot.bot_rules (bot_id, rule_type, pattern, instruction, priority)
    VALUES
    (v_bot_id, 'url_contains', '/pricing', 'The user is on the pricing page. Focus on explaining pricing plans, comparing tiers, and helping them choose the right plan. Offer to connect them with sales if they need a custom quote.', 10),
    (v_bot_id, 'url_contains', '/docs', 'The user is on the documentation page. Be technical and precise. Help them find the right documentation section. Reference API endpoints and code examples when relevant.', 10),
    (v_bot_id, 'url_contains', '/dashboard', 'The user is on their dashboard. Help them understand metrics, customize their view, or troubleshoot any data issues they see.', 5),
    (v_bot_id, 'fallback', '*', 'The user is browsing the website. Be welcoming and helpful. Guide them to relevant features and answer general questions.', 0)
    ON CONFLICT DO NOTHING;

    RAISE NOTICE 'Seeded rules for bot %', v_bot_id;
END $$;


-- ── Record migration ─────────────────────────────────────────────────

INSERT INTO ag_system.migration_history (version, script_name, description)
VALUES ('V004', 'V004_create_bot_schema.sql', 'Chatbot platform schema (ag_bot) with shared knowledge')
ON CONFLICT DO NOTHING;

COMMIT;
