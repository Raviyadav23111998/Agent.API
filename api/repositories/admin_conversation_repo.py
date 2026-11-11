"""
Admin Conversations Repository — All-users conversation browsing.
═══════════════════════════════════════════════════════════════════
Table: ag_system.conversations
Unlike the user-scoped ChatRepository, this shows ALL conversations
across all users for admin oversight.
"""
import logging
from typing import List, Dict, Optional, Tuple

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class AdminConversationRepository:
    """Data access for admin-level conversation browsing (cross-user)."""

    def __init__(self, db: TenantDB):
        self._db = db

    def list_conversations(
        self,
        user_id: Optional[int] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        take: int = 50,
    ) -> Tuple[int, List[Dict]]:
        """List all conversations with optional filtering. Returns (total, rows)."""
        conditions = ["is_archived = false"]
        params: list = []

        if user_id is not None:
            conditions.append("c.user_id = %s")
            params.append(user_id)
        if source:
            conditions.append("c.source = %s")
            params.append(source)
        if search:
            conditions.append("c.title ILIKE %s")
            params.append(f"%{search}%")

        where = f"WHERE {' AND '.join(conditions)}"

        count_row = self._db.fetch_one(
            f"SELECT COUNT(*) as cnt FROM ag_system.conversations c {where}", params
        )
        total = count_row["cnt"] if count_row else 0

        rows = self._db.fetch_all(f"""
            SELECT c.conversation_id, c.title, c.user_id, c.agent_id,
                   c.model, c.message_count, c.source,
                   c.created_at, c.updated_at
            FROM ag_system.conversations c
            {where}
            ORDER BY c.updated_at DESC
            LIMIT %s OFFSET %s
        """, params + [take, skip])

        return total, rows

    def get_conversation_detail(self, conversation_id: str) -> Optional[Dict]:
        """Get conversation with its messages (admin — no user scoping)."""
        conv = self._db.fetch_one("""
            SELECT conversation_id, title, user_id, agent_id, model,
                   message_count, source, is_archived, created_at, updated_at
            FROM ag_system.conversations
            WHERE conversation_id = %s
        """, (conversation_id,))
        if not conv:
            return None

        messages = self._db.fetch_all("""
            SELECT message_id, role, content, tool_calls, token_count, created_at
            FROM ag_system.messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC
        """, (conversation_id,))
        conv["messages"] = messages
        return conv

    def delete_conversation(self, conversation_id: str):
        """Delete any conversation (admin — no user scoping)."""
        self._db.execute(
            "DELETE FROM ag_system.conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
