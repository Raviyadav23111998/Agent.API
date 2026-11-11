"""
Dashboard Repository — Data access for admin dashboard statistics.
═══════════════════════════════════════════════════════════════════════
Tables: ag_auth.users, ag_system.conversations, ag_brain.documents,
        ag_system.memories, ag_system.cron_jobs, ag_system.applications,
        ag_bot.bots, ag_system.agents, ag_system.action_audit
"""
import logging
from typing import List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class DashboardRepository:
    """Data access for admin dashboard aggregate statistics."""

    def __init__(self, db: TenantDB):
        self._db = db


    def get_users_count(self) -> int:
        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_auth.users WHERE is_active = true"
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_conversations_count(self) -> int:
        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_system.conversations WHERE is_archived = false"
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_brain_docs_count(self) -> int:
        try:
            row = self._db.fetch_one("SELECT COUNT(*) as cnt FROM ag_brain.documents")
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_memories_count(self) -> int:
        try:
            row = self._db.fetch_one("SELECT COUNT(*) as cnt FROM ag_system.memories")
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_active_crons_count(self) -> int:
        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_system.cron_jobs WHERE enabled = true"
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_apps_count(self) -> int:
        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_system.applications WHERE is_active = true"
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_bots_count(self) -> int:
        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_bot.bots WHERE is_active = true"
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0

    def get_agents_count(self) -> int:
        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_system.agents WHERE is_active = true"
            )
            return row["cnt"] if row else 0
        except Exception:
            return 0


    def get_recent_audit(self, limit: int = 20) -> List[Dict]:
        try:
            return self._db.fetch_all("""
                SELECT audit_id, user_id, tool_name, side_effect, args_summary,
                       approved, status, created_at
                FROM ag_system.action_audit
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
        except Exception:
            return []

    def get_recent_conversations(self, limit: int = 10) -> List[Dict]:
        try:
            return self._db.fetch_all("""
                SELECT conversation_id, title, user_id, message_count,
                       created_at, updated_at
                FROM ag_system.conversations
                WHERE is_archived = false
                ORDER BY updated_at DESC
                LIMIT %s
            """, (limit,))
        except Exception:
            return []
