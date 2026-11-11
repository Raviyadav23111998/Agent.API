"""
Admin Conversations Service — Business logic for admin conversation browser.
"""
from typing import Dict, Optional

from api.repositories.admin_conversation_repo import AdminConversationRepository


class AdminConversationService:
    def __init__(self, repo: AdminConversationRepository):
        self._repo = repo

    async def list_conversations(
        self,
        user_id: Optional[int] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        take: int = 50,
    ) -> Dict:
        """List all conversations with pagination."""
        total, rows = self._repo.list_conversations(
            user_id=user_id, source=source, search=search,
            skip=skip, take=take,
        )
        items = [
            {
                "conversationId": r["conversation_id"],
                "title": r.get("title"),
                "userId": r["user_id"],
                "agentId": r.get("agent_id"),
                "model": r.get("model"),
                "messageCount": r.get("message_count", 0),
                "source": r.get("source", "web"),
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
                "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
            }
            for r in rows
        ]
        return {"total": total, "skip": skip, "take": take, "items": items}

    async def get_detail(self, conversation_id: str) -> Optional[Dict]:
        """Get conversation with messages (admin view)."""
        detail = self._repo.get_conversation_detail(conversation_id)
        if not detail:
            return None
        return {
            "conversationId": detail["conversation_id"],
            "title": detail.get("title"),
            "userId": detail["user_id"],
            "agentId": detail.get("agent_id"),
            "model": detail.get("model"),
            "messageCount": detail.get("message_count", 0),
            "source": detail.get("source", "web"),
            "isArchived": detail.get("is_archived", False),
            "createdAt": detail["created_at"].isoformat() if detail.get("created_at") else None,
            "updatedAt": detail["updated_at"].isoformat() if detail.get("updated_at") else None,
            "messages": [
                {
                    "messageId": m["message_id"],
                    "role": m["role"],
                    "content": m.get("content", ""),
                    "tokenCount": m.get("token_count", 0),
                    "createdAt": m["created_at"].isoformat() if m.get("created_at") else None,
                }
                for m in detail.get("messages", [])
            ],
        }

    async def delete_conversation(self, conversation_id: str):
        """Admin-delete a conversation."""
        self._repo.delete_conversation(conversation_id)
