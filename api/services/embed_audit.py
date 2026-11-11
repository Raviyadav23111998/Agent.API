"""
Embed Action Audit — best-effort logging of copilot page actions (Phase 4).
═══════════════════════════════════════════════════════════════════════════════
Logs every copilot action on the host page — page_act (the batched fill/
select/click) and page_navigate — plus blocked/approved/denied decisions from
the execution policy engine.

All writes are fire-and-forget (best-effort) to avoid slowing down the
agent turn. Reads are used by Phase 5 admin audit viewer and analytics.

Table: ag_bot.embed_action_audit (V026_embed_audit.sql).
"""

import logging
from typing import Optional

logger = logging.getLogger("agent.embed.audit")

AUDITABLE_TOOLS = frozenset({"page_act", "page_navigate"})


class EmbedAuditRepo:
    """Repository for embed action audit log entries."""

    def __init__(self, db):
        self._db = db

    def write_action(
        self,
        integration_id: int,
        session_id: str,
        tool_name: str,
        target_label: Optional[str] = None,
        tool_args: Optional[str] = None,
        result: Optional[str] = None,
        status: str = "executed",
        client_ip: Optional[str] = None,
        end_user_id: Optional[str] = None,
    ):
        """Write an audit log entry (best-effort, fire-and-forget).

        Args:
            integration_id: The integration (bot_id).
            session_id: Embed session identifier.
            tool_name: The tool that was called (e.g. page_act).
            target_label: The button/link label or route.
            tool_args: Truncated args summary.
            result: Truncated result.
            status: 'executed', 'blocked', 'approved', 'denied'.
            client_ip: Client IP address.
            end_user_id: Verified end-user identity if available.
        """
        try:
            self._db.execute(
                """
                INSERT INTO ag_bot.embed_action_audit
                    (integration_id, session_id, tool_name, target_label,
                     tool_args, result, status, client_ip, end_user_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    integration_id,
                    session_id,
                    tool_name,
                    (target_label or "")[:200],
                    (tool_args or "")[:500],
                    (result or "")[:500],
                    status,
                    client_ip,
                    end_user_id,
                ),
            )
        except Exception as e:
            logger.warning("Embed audit write failed (non-critical): %s", e)

    def get_actions(self, integration_id: int, limit: int = 100,
                    offset: int = 0) -> list:
        """Read audit entries for an integration (Phase 5 admin viewer).

        Returns list of dicts, newest first.
        """
        try:
            return self._db.fetch_all(
                """
                SELECT id, session_id, tool_name, target_label, tool_args,
                       result, status, client_ip, end_user_id, created_at
                FROM ag_bot.embed_action_audit
                WHERE integration_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (integration_id, limit, offset),
            ) or []
        except Exception as e:
            logger.warning("Embed audit read failed: %s", e)
            return []
