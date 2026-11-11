"""
Bot Repository — Chatbot data access layer.
═══════════════════════════════════════════════
Tables: ag_bot.bots, ag_bot.bot_rules, ag_bot.bot_knowledge_links,
        ag_bot.bot_conversations, ag_bot.bot_messages
"""
import logging
import hashlib
from typing import Optional, List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class BotRepository:
    """Data access for the chatbot platform."""

    def __init__(self, db: TenantDB):
        self._db = db


    def get_bot_by_token(self, api_token: str) -> Optional[Dict]:
        """Validate API token (via SHA-256 hash) and return bot config."""
        token_hash = hashlib.sha256(api_token.encode('utf-8')).hexdigest()
        return self._db.fetch_one("""
            SELECT bot_id, bot_uuid, name, description,
                   allowed_domains, system_prompt, welcome_message,
                   model, theme_color, max_context_docs, is_active,
                   app_id, persona_id, created_at, updated_at
            FROM ag_bot.bots
            WHERE api_token_hash = %s AND is_active = TRUE
        """, (token_hash,))

    def get_bot_by_id(self, bot_id: int) -> Optional[Dict]:
        return self._db.fetch_one("""
            SELECT bot_id, bot_uuid, name, description, system_prompt,
                   welcome_message, model, theme_color, max_context_docs,
                   is_active, app_id, created_at
            FROM ag_bot.bots WHERE bot_id = %s
        """, (bot_id,))


    def get_bot_rules(self, bot_id: int, page_url: str = None) -> List[Dict]:
        """Get matched rules for the current page URL.

        Matching logic:
        - 'url_contains': page_url ILIKE '%pattern%'
        - 'url_exact': page_url = pattern
        - 'fallback': always matches
        - 'url_regex': page_url ~ pattern (PostgreSQL regex)

        Returns rules ordered by priority (highest first).
        """
        if not page_url:
            return self._db.fetch_all("""
                SELECT rule_id, rule_type, pattern, instruction, priority
                FROM ag_bot.bot_rules
                WHERE bot_id = %s AND is_active = TRUE AND rule_type = 'fallback'
                ORDER BY priority DESC
            """, (bot_id,))

        return self._db.fetch_all("""
            SELECT rule_id, rule_type, pattern, instruction, priority
            FROM ag_bot.bot_rules
            WHERE bot_id = %s AND is_active = TRUE
              AND (
                  (rule_type = 'url_contains' AND %s ILIKE '%%' || pattern || '%%')
                  OR (rule_type = 'url_exact' AND %s = pattern)
                  OR (rule_type = 'url_regex' AND %s ~ pattern)
                  OR rule_type = 'fallback'
              )
            ORDER BY priority DESC
        """, (bot_id, page_url, page_url, page_url))


    def get_bot_knowledge_docs(self, bot_id: int, page_url: str = None,
                               limit: int = 5) -> List[Dict]:
        """
        Get the most relevant pre-assigned knowledge documents for a bot.
        Strictly scoped to the bot's app_id — no global docs.
        """
        return self._db.fetch_all("""
            SELECT d.doc_id, d.title, d.source_path, d.doc_type,
                   LEFT(d.content, 2000) AS content
            FROM ag_brain.documents d
            JOIN ag_bot.bots b ON b.bot_id = %s
            WHERE d.status = 'indexed'
              AND b.app_id IS NOT NULL
              AND d.app_id = b.app_id
            ORDER BY d.created_at DESC LIMIT %s
        """, (bot_id, limit))

    def search_bot_knowledge(self, bot_id: int, query: str,
                              page_url: str = None, limit: int = 5) -> List[Dict]:
        """Full-text search across this bot's application knowledge docs only."""
        return self._db.fetch_all("""
            SELECT d.doc_id, d.title, LEFT(d.content, 2000) AS content,
                   d.doc_type, d.tags,
                   ts_rank(d.fts_vector, plainto_tsquery('english', %s)) AS rank
            FROM ag_brain.documents d
            JOIN ag_bot.bots b ON b.bot_id = %s
            WHERE d.status = 'indexed'
              AND d.fts_vector @@ plainto_tsquery('english', %s)
              AND b.app_id IS NOT NULL
              AND d.app_id = b.app_id
            ORDER BY rank DESC LIMIT %s
        """, (query, bot_id, query, limit))


    def get_or_create_conversation(self, bot_id: int, session_id: str,
                                    page_url: str = None) -> Dict:
        """Get existing conversation for this session, or create new one."""
        conv = self._db.fetch_one("""
            SELECT conversation_id, bot_id, session_id, page_url,
                   message_count, created_at, updated_at
            FROM ag_bot.bot_conversations
            WHERE bot_id = %s AND session_id = %s
            ORDER BY updated_at DESC LIMIT 1
        """, (bot_id, session_id))

        if conv:
            if page_url and page_url != conv.get('page_url'):
                self._db.execute("""
                    UPDATE ag_bot.bot_conversations SET page_url = %s
                    WHERE conversation_id = %s
                """, (page_url, conv['conversation_id']))
            return conv

        return self._db.execute_returning("""
            INSERT INTO ag_bot.bot_conversations (bot_id, session_id, page_url)
            VALUES (%s, %s, %s)
            RETURNING conversation_id, bot_id, session_id, page_url,
                      message_count, created_at, updated_at
        """, (bot_id, session_id, page_url))

    def add_message(self, conversation_id: str, role: str, content: str,
                    token_count: int = 0) -> Dict:
        """Add a message and increment count."""
        msg = self._db.execute_returning("""
            INSERT INTO ag_bot.bot_messages (conversation_id, role, content, token_count)
            VALUES (%s, %s, %s, %s)
            RETURNING message_id, conversation_id, role, content, created_at
        """, (conversation_id, role, content, token_count))

        self._db.execute("""
            UPDATE ag_bot.bot_conversations
            SET message_count = message_count + 1
            WHERE conversation_id = %s
        """, (conversation_id,))

        return msg

    def get_messages(self, conversation_id: str, limit: int = 30) -> List[Dict]:
        """Get conversation messages in chronological order."""
        return self._db.fetch_all("""
            SELECT message_id, role, content, token_count, created_at
            FROM ag_bot.bot_messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC LIMIT %s
        """, (conversation_id, limit))

    def get_recent_messages(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages for context building."""
        rows = self._db.fetch_all("""
            SELECT role, content FROM ag_bot.bot_messages
            WHERE conversation_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (conversation_id, limit))
        return list(reversed(rows))
