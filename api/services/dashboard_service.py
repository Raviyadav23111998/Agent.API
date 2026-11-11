"""
Dashboard Service — Business logic for admin dashboard statistics.
"""
from typing import Dict
from api.repositories.dashboard_repo import DashboardRepository


class DashboardService:
    def __init__(self, repo: DashboardRepository):
        self._repo = repo

    async def get_stats(self) -> Dict:
        """Aggregate all platform statistics for the admin dashboard."""
        stats = {
            "users_count": self._repo.get_users_count(),
            "conversations_count": self._repo.get_conversations_count(),
            "brain_docs_count": self._repo.get_brain_docs_count(),
            "memories_count": self._repo.get_memories_count(),
            "active_crons": self._repo.get_active_crons_count(),
            "apps_count": self._repo.get_apps_count(),
            "bots_count": self._repo.get_bots_count(),
            "agents_count": self._repo.get_agents_count(),
        }

        raw_audit = self._repo.get_recent_audit(limit=20)
        stats["recent_audit"] = [
            {
                "auditId": r["audit_id"],
                "userId": r["user_id"],
                "toolName": r["tool_name"],
                "sideEffect": r["side_effect"],
                "argsSummary": r.get("args_summary", ""),
                "approved": r.get("approved"),
                "status": r["status"],
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in raw_audit
        ]

        raw_convos = self._repo.get_recent_conversations(limit=10)
        stats["recent_conversations"] = [
            {
                "conversationId": r["conversation_id"],
                "title": r.get("title"),
                "userId": r["user_id"],
                "messageCount": r.get("message_count", 0),
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
                "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
            }
            for r in raw_convos
        ]

        return stats
