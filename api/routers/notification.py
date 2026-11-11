import logging
from typing import Dict, Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notification", tags=["Notification"])


def _get_notification_service(request: Request):
    return request.app.state.notification_service


class EmailTemplateRequest(BaseModel):
    template_id: Optional[int] = None
    type: str
    subject: str
    body: str
    data_fields: str


@router.get("/unread")
async def get_unread_notifications(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_notification_service(request)
    current_uid = int(current_user.get("user_ID", 0))
    return svc.get_unread_notifications(current_uid)


@router.put("/read/{recipient_id}")
async def mark_notification_as_read(
    recipient_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_notification_service(request)
    current_uid = int(current_user.get("user_ID", 0))
    svc.mark_as_read(recipient_id, current_uid)
    return {"message": "Notification marked as read"}


@router.post("/templates/email")
@router.put("/templates/email/{template_id}")
async def add_update_email_template(
    req: EmailTemplateRequest,
    request: Request,
    template_id: Optional[int] = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_notification_service(request)
    current_uid = int(current_user.get("user_ID", 0))
    
    if template_id:
        req.template_id = template_id
        
    result_id = svc.add_update_email_template(
        type_name=req.type,
        subject=req.subject,
        body=req.body,
        data_fields=req.data_fields,
        current_user_id=current_uid,
        template_id=req.template_id
    )
    return {"template_id": result_id}
