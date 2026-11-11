"""
Audit Repository — Data access for the action audit trail.
═══════════════════════════════════════════════════════════
Table: ag_system.action_audit
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class AuditRepository:
    """Data access for the action audit log (ag_system.action_audit)."""

    def __init__(self, db: TenantDB):
        self._db = db

    def list_entries(
        self,
        tool_name: Optional[str] = None,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        side_effect: Optional[str] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        skip: int = 0,
        take: int = 50,
    ) -> Tuple[int, List[Dict]]:
        """
        Return (total_count, rows) with optional filtering and pagination.
        Results ordered by created_at DESC.
        """
        conditions = []
        params: list = []

        if tool_name:
            conditions.append("tool_name = %s")
            params.append(tool_name)
        if user_id is not None:
            conditions.append("user_id = %s")
            params.append(user_id)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if side_effect:
            conditions.append("side_effect = %s")
            params.append(side_effect)
        if from_dt:
            conditions.append("created_at >= %s")
            params.append(from_dt)
        if to_dt:
            conditions.append("created_at <= %s")
            params.append(to_dt)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_row = self._db.fetch_one(
            f"SELECT COUNT(*) as cnt FROM ag_system.action_audit {where}", params
        )
        total = count_row["cnt"] if count_row else 0

        rows = self._db.fetch_all(f"""
            SELECT audit_id, user_id, conversation_id, tool_name, side_effect,
                   args_summary, approved, status, created_at
            FROM ag_system.action_audit
            {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [take, skip])

        return total, rows

    def get_summary(self) -> Dict:
        """Aggregate audit stats: by status, side_effect, top tools, total count."""
        result: Dict = {}

        try:
            rows = self._db.fetch_all("""
                SELECT status, COUNT(*) as cnt
                FROM ag_system.action_audit
                GROUP BY status ORDER BY cnt DESC
            """)
            result["by_status"] = {r["status"]: r["cnt"] for r in rows}
        except Exception:
            result["by_status"] = {}

        try:
            rows = self._db.fetch_all("""
                SELECT side_effect, COUNT(*) as cnt
                FROM ag_system.action_audit
                GROUP BY side_effect ORDER BY cnt DESC
            """)
            result["by_side_effect"] = {r["side_effect"]: r["cnt"] for r in rows}
        except Exception:
            result["by_side_effect"] = {}

        try:
            rows = self._db.fetch_all("""
                SELECT tool_name, COUNT(*) as cnt
                FROM ag_system.action_audit
                GROUP BY tool_name ORDER BY cnt DESC LIMIT 10
            """)
            result["top_tools"] = [
                {"tool": r["tool_name"], "count": r["cnt"]} for r in rows
            ]
        except Exception:
            result["top_tools"] = []

        try:
            row = self._db.fetch_one(
                "SELECT COUNT(*) as cnt FROM ag_system.action_audit"
            )
            result["total"] = row["cnt"] if row else 0
        except Exception:
            result["total"] = 0

        return result
