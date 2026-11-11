"""
Admin Audit Log Router — Browse and filter the action audit trail.
══════════════════════════════════════════════════════════════════════
Admin-only endpoints for paginated audit log browsing via AuditService.

Security: Admin-only (require_admin dependency).
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Request, Query

from api.middleware.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/audit", tags=["Admin Audit"])


def _get_audit_service(request: Request):
    return request.app.state.audit_service


@router.get("", summary="Browse audit log with pagination and filters")
async def list_audit(
    request: Request,
    current_user: Dict = Depends(require_admin),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    side_effect: Optional[str] = Query(None, description="Filter by side effect"),
    from_date: Optional[str] = Query(None, description="Start date (ISO)", alias="from"),
    to_date: Optional[str] = Query(None, description="End date (ISO)", alias="to"),
    skip: int = Query(0, ge=0),
    take: int = Query(50, ge=1, le=200),
):
    svc = _get_audit_service(request)
    return await svc.list_entries(
        tool_name=tool_name,
        user_id=user_id,
        status=status,
        side_effect=side_effect,
        from_date=from_date,
        to_date=to_date,
        skip=skip,
        take=take,
    )


@router.get("/summary", summary="Audit log summary statistics")
async def audit_summary(
    request: Request,
    current_user: Dict = Depends(require_admin),
):
    svc = _get_audit_service(request)
    return await svc.get_summary()
