import logging
import json
from typing import Optional, Dict, List
from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class NotificationRepository:
    def __init__(self, db: TenantDB):
        self._db = db

    def get_email_template_by_type(self, template_type: str) -> Optional[Dict]:
        return self._db.fetch_one("""
            SELECT * FROM ag_notification.email_notifications
            WHERE type = %s
        """, (template_type,))
        
    def add_update_email_template(self, type_name: str, subject: str, body: str, data_fields: str, current_user_id: int, template_id: Optional[int] = None) -> int:
        if template_id:
            self._db.execute("""
                UPDATE ag_notification.email_notifications SET
                    type = %s, subject = %s, body = %s, data_fields = %s,
                    updated_by = %s, updation_date = ag_common.utc_now()
                WHERE email_template_id = %s
            """, (type_name, subject, body, data_fields, current_user_id, template_id))
            return template_id
        else:
            row = self._db.execute_returning("""
                INSERT INTO ag_notification.email_notifications (
                    type, subject, body, data_fields, created_by
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING email_template_id
            """, (type_name, subject, body, data_fields, current_user_id))
            return row['email_template_id']

    def create_notification(
        self,
        sender_id: int,
        target_scope: str,
        final_title: str,
        final_body: str,
        data_payload: Dict,
        recipient_user_ids: List[int],
        target_reference_id: Optional[int] = None,
        template_id: Optional[int] = None,
    ) -> int:
        """Create a notification campaign and recipients."""
        payload_json = json.dumps(data_payload) if data_payload else None
        
        row = self._db.execute_returning("""
            INSERT INTO ag_notification.notifications (
                template_id, sender_id, target_scope, target_reference_id,
                final_title, final_body, data_payload, status, total_recipients
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
            RETURNING notification_id
        """, (template_id, sender_id, target_scope, target_reference_id,
              final_title, final_body, payload_json, len(recipient_user_ids)))
        
        notification_id = row['notification_id']
        
        for uid in recipient_user_ids:
            self._db.execute("""
                INSERT INTO ag_notification.notification_recipients (
                    notification_id, user_id
                ) VALUES (%s, %s)
                ON CONFLICT (notification_id, user_id) DO NOTHING
            """, (notification_id, uid))
            
        return notification_id

    def get_unread_notifications(self, user_id: int) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT n.notification_id, n.final_title, n.final_body, n.created_at, n.data_payload,
                   r.read_at, r.recipient_id
            FROM ag_notification.notification_recipients r
            JOIN ag_notification.notifications n ON n.notification_id = r.notification_id
            WHERE r.user_id = %s AND r.read_at IS NULL
            ORDER BY n.created_at DESC
            LIMIT 50
        """, (user_id,))
        
    def mark_as_read(self, recipient_id: int, user_id: int) -> bool:
        self._db.execute("""
            UPDATE ag_notification.notification_recipients 
            SET read_at = ag_common.utc_now(), updated_at = ag_common.utc_now()
            WHERE recipient_id = %s AND user_id = %s
        """, (recipient_id, user_id))
        return True
