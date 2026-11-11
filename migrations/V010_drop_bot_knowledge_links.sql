-- V010_drop_bot_knowledge_links.sql
-- 
-- Bot knowledge is now managed purely at the Application (app_id) level.
-- Bots automatically inherit access to all knowledge documents assigned
-- to their application, so the many-to-many bot_knowledge_links table is obsolete.

DROP TABLE IF EXISTS ag_bot.bot_knowledge_links CASCADE;
