"""
Bot Admin Repository — Management data access layer.
════════════════════════════════════════════════════
"""
import logging
import secrets
import hashlib
from typing import Optional, List, Dict
from core.tenant_db import TenantDB
from api.schemas.bot_admin import BotCreateRequest, BotUpdateRequest

logger = logging.getLogger(__name__)

class BotAdminRepository:
    def __init__(self, db: TenantDB):
        self._db = db

    def _generate_api_token(self) -> str:
        """Generate a secure, unique API token."""
        return f"ag_bot_{secrets.token_urlsafe(24)}"

    @staticmethod
    def _hash_token(token: str) -> str:
        """SHA-256 hash for secure storage. Never store raw tokens."""
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def create_bot(self, data: BotCreateRequest, created_by: int) -> Dict:
        """Create a new bot. Returns the raw api_token ONCE (not stored)."""
        raw_token = self._generate_api_token()
        token_hash = self._hash_token(raw_token)
        row = self._db.execute_returning("""
            INSERT INTO ag_bot.bots (
                name, description, api_token, api_token_hash, allowed_domains,
                system_prompt, welcome_message, model, theme_color,
                max_context_docs, is_active, created_by, app_id
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            ) RETURNING *
        """, (
            data.name, data.description, raw_token, token_hash, data.allowed_domains,
            data.system_prompt, data.welcome_message, data.model, data.theme_color,
            data.max_context_docs, data.is_active, created_by, data.app_id
        ))
        row["api_token"] = raw_token
        return row

    def update_bot(self, bot_id: int, data: BotUpdateRequest, user_id: int) -> Optional[Dict]:
        """Update an existing bot. Ensures only the creator can update."""
        return self._db.execute_returning("""
            UPDATE ag_bot.bots SET
                name = %s, description = %s, allowed_domains = %s,
                system_prompt = %s, welcome_message = %s, model = %s,
                theme_color = %s, max_context_docs = %s, is_active = %s,
                app_id = %s
            WHERE bot_id = %s AND created_by = %s
            RETURNING *
        """, (
            data.name, data.description, data.allowed_domains,
            data.system_prompt, data.welcome_message, data.model,
            data.theme_color, data.max_context_docs, data.is_active,
            data.app_id,
            bot_id, user_id
        ))

    def list_bots(self, user_id: int) -> List[Dict]:
        """List all bots created by the user."""
        return self._db.fetch_all("""
            SELECT * FROM ag_bot.bots
            WHERE created_by = %s
            ORDER BY created_at DESC
        """, (user_id,))

    def get_bot(self, bot_id: int, user_id: int) -> Optional[Dict]:
        """Get a specific bot."""
        return self._db.fetch_one("""
            SELECT * FROM ag_bot.bots
            WHERE bot_id = %s AND created_by = %s
        """, (bot_id, user_id))

    def delete_bot(self, bot_id: int, user_id: int):
        """Delete a bot."""
        self._db.execute("""
            DELETE FROM ag_bot.bots
            WHERE bot_id = %s AND created_by = %s
        """, (bot_id, user_id))


    def get_rules(self, bot_id: int, user_id: int) -> List[Dict]:
        """Verify ownership, then fetch rules."""
        bot = self.get_bot(bot_id, user_id)
        if not bot:
            return []
        return self._db.fetch_all("""
            SELECT * FROM ag_bot.bot_rules
            WHERE bot_id = %s
            ORDER BY priority DESC
        """, (bot_id,))

    def set_rules(self, bot_id: int, user_id: int, rules: List[Dict]):
        """Replace all rules for a bot."""
        bot = self.get_bot(bot_id, user_id)
        if not bot:
            raise ValueError("Bot not found or access denied")
        
        self._db.execute("DELETE FROM ag_bot.bot_rules WHERE bot_id = %s", (bot_id,))
        for r in rules:
            self._db.execute("""
                INSERT INTO ag_bot.bot_rules (bot_id, rule_type, pattern, instruction, priority, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (bot_id, r['rule_type'], r['pattern'], r['instruction'], r['priority'], r['is_active']))


