"""
Admin Conversations Router — Browse all conversations across all users.
═══════════════════════════════════════════════════════════════════════
Admin-only endpoints for conversation oversight. Unlike the user-scoped
chat router, these show ALL conversations.

Security: Admin-only (require_admin dependency).
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query

from api.middleware.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/conversations", tags=["Admin Conversations"])


def _get_service(request: Request):
    return request.app.state.admin_conversation_service


@router.get("", summary="List all conversations (admin)")
async def list_conversations(
    request: Request,
    current_user: Dict = Depends(require_admin),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    source: Optional[str] = Query(None, description="Filter by source (web, cli, api)"),
    search: Optional[str] = Query(None, description="Search by title"),
    skip: int = Query(0, ge=0),
    take: int = Query(50, ge=1, le=200),
):
    svc = _get_service(request)
    return await svc.list_conversations(
        user_id=user_id, source=source, search=search,
        skip=skip, take=take,
    )


@router.get("/{conversation_id}", summary="Get conversation detail (admin)")
async def get_conversation(
    conversation_id: str,
    request: Request,
    current_user: Dict = Depends(require_admin),
):
    svc = _get_service(request)
    detail = await svc.get_detail(conversation_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.delete("/{conversation_id}", summary="Delete conversation (admin)")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    current_user: Dict = Depends(require_admin),
):
    svc = _get_service(request)
    await svc.delete_conversation(conversation_id)
    return {"message": "Conversation deleted"}
