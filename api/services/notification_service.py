import logging
from typing import Dict, List, Optional

from api.repositories.notification_repo import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self._repo = repo

    async def send_email(self, template_type: str, data_payload: Dict, recipient_email: str, recipient_user_id: int):
        """
        Mimics SMSystems IEmailNotificationService.
        Retrieves template, injects data_payload, and queues an email notification.
        In a real production environment, this would call SMTP or an external API like SendGrid.
        For now, we log the email and store it in ag_notification.notifications.
        """
        template = self._repo.get_email_template_by_type(template_type)
        if not template:
            logger.warning(f"Email template '{template_type}' not found. Using fallback.")
            subject = f"Notification: {template_type}"
            body = f"Payload: {data_payload}"
        else:
            subject = template.get('subject', f"Notification: {template_type}")
            body = template.get('body', "")
            for key, val in data_payload.items():
                body = body.replace(f"{{{{{key}}}}}", str(val))
                subject = subject.replace(f"{{{{{key}}}}}", str(val))

        logger.info(f"Sending email '{subject}' to {recipient_email}")

        
        self._repo.create_notification(
            sender_id=0,
            target_scope="USER",
            final_title=subject,
            final_body=body,
            data_payload=data_payload,
            recipient_user_ids=[recipient_user_id],
            template_id=template.get('email_template_id') if template else None
        )
        return True

    def get_unread_notifications(self, user_id: int) -> List[Dict]:
        return self._repo.get_unread_notifications(user_id)

    def mark_as_read(self, recipient_id: int, user_id: int) -> bool:
        return self._repo.mark_as_read(recipient_id, user_id)
        
    def add_update_email_template(self, type_name: str, subject: str, body: str, data_fields: str, current_user_id: int, template_id: Optional[int] = None) -> int:
        return self._repo.add_update_email_template(type_name, subject, body, data_fields, current_user_id, template_id)
