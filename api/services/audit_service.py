"""
Audit Service — Business logic for the admin audit log browser.
"""
from datetime import datetime
from typing import Dict, Optional

from api.repositories.audit_repo import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository):
        self._repo = repo

    async def list_entries(
        self,
        tool_name: Optional[str] = None,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        side_effect: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        skip: int = 0,
        take: int = 50,
    ) -> Dict:
        """List audit entries with optional filtering and pagination."""

        from_dt = None
        to_dt = None
        if from_date:
            from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
        if to_date:
            to_dt = datetime.fromisoformat(to_date.replace('Z', '+00:00'))

        total, rows = self._repo.list_entries(
            tool_name=tool_name,
            user_id=user_id,
            status=status,
            side_effect=side_effect,
            from_dt=from_dt,
            to_dt=to_dt,
            skip=skip,
            take=take,
        )

        items = [
            {
                "auditId": r["audit_id"],
                "userId": r["user_id"],
                "conversationId": r.get("conversation_id"),
                "toolName": r["tool_name"],
                "sideEffect": r["side_effect"],
                "argsSummary": r.get("args_summary", ""),
                "approved": r.get("approved"),
                "status": r["status"],
                "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
            }
            for r in rows
        ]

        return {
            "total": total,
            "skip": skip,
            "take": take,
            "items": items,
        }

    async def get_summary(self) -> Dict:
        """Return aggregate audit statistics."""
        return self._repo.get_summary()
