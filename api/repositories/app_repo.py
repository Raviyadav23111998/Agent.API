"""
Application Repository — CRUD for ag_system.applications.
"""
import logging
from typing import List, Dict, Any, Optional

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class AppRepository:
    """Repository for managing Applications."""

    def __init__(self, db: TenantDB):
        self._db = db

    def list_apps(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """List all applications with computed counts."""
        where = "" if include_inactive else "WHERE a.is_active = TRUE"
        return self._db.fetch_all(f"""
            SELECT a.*,
                   a.app_uuid::TEXT AS app_uuid,
                   COALESCE(d.cnt, 0) AS doc_count,
                   COALESCE(b.cnt, 0) AS bot_count,
                   COALESCE(c.cnt, 0) AS cron_count
            FROM ag_system.applications a
            LEFT JOIN (
                SELECT app_id, COUNT(*) AS cnt FROM ag_brain.documents GROUP BY app_id
            ) d ON d.app_id = a.app_id
            LEFT JOIN (
                SELECT app_id, COUNT(*) AS cnt FROM ag_bot.bots GROUP BY app_id
            ) b ON b.app_id = a.app_id
            LEFT JOIN (
                SELECT app_id, COUNT(*) AS cnt FROM ag_agents.cron_jobs GROUP BY app_id
            ) c ON c.app_id = a.app_id
            {where}
            ORDER BY a.app_id
        """)

    def get_app(self, app_id: int) -> Optional[Dict[str, Any]]:
        """Get a single application by ID."""
        return self._db.fetch_one("""
            SELECT a.*,
                   a.app_uuid::TEXT AS app_uuid,
                   COALESCE(d.cnt, 0) AS doc_count,
                   COALESCE(b.cnt, 0) AS bot_count,
                   COALESCE(c.cnt, 0) AS cron_count
            FROM ag_system.applications a
            LEFT JOIN (
                SELECT app_id, COUNT(*) AS cnt FROM ag_brain.documents GROUP BY app_id
            ) d ON d.app_id = a.app_id
            LEFT JOIN (
                SELECT app_id, COUNT(*) AS cnt FROM ag_bot.bots GROUP BY app_id
            ) b ON b.app_id = a.app_id
            LEFT JOIN (
                SELECT app_id, COUNT(*) AS cnt FROM ag_agents.cron_jobs GROUP BY app_id
            ) c ON c.app_id = a.app_id
            WHERE a.app_id = %s
        """, (app_id,))

    def create_app(self, name: str, description: str = "", app_type: str = "internal",
                   llm_model: str = None, max_tokens_day: int = 0,
                   max_documents: int = 0, created_by: int = None) -> Dict[str, Any]:
        """Create a new application."""
        row = self._db.execute_returning("""
            INSERT INTO ag_system.applications
                (name, description, app_type, llm_model, max_tokens_day, max_documents, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *, app_uuid::TEXT AS app_uuid
        """, (name, description, app_type, llm_model, max_tokens_day, max_documents, created_by))
        row['doc_count'] = 0
        row['bot_count'] = 0
        row['cron_count'] = 0
        logger.info("app.created: id=%s name=%s type=%s", row['app_id'], name, app_type)
        return row

    def update_app(self, app_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """Update an application. Only updates fields present in kwargs."""
        allowed = {'name', 'description', 'app_type', 'llm_model',
                   'max_tokens_day', 'max_documents', 'is_active',
                   'llm_profile_id'}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return self.get_app(app_id)

        set_clauses = ", ".join(f"{k} = %s" for k in updates)
        set_clauses += ", updated_at = NOW()"
        params = list(updates.values()) + [app_id]

        self._db.execute(
            f"UPDATE ag_system.applications SET {set_clauses} WHERE app_id = %s",
            tuple(params)
        )
        logger.info("app.updated: id=%s fields=%s", app_id, list(updates.keys()))
        return self.get_app(app_id)

    def delete_app(self, app_id: int) -> bool:
        """Soft-delete an application (set is_active = FALSE)."""
        if app_id == 1:
            raise ValueError("Cannot delete the default application")
        rows = self._db.execute(
            "UPDATE ag_system.applications SET is_active = FALSE, updated_at = NOW() WHERE app_id = %s",
            (app_id,)
        )
        logger.info("app.deleted: id=%s", app_id)
        return rows > 0
