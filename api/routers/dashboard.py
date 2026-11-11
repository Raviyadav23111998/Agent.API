"""
Admin Dashboard Router — Aggregated admin stats + health overview.
══════════════════════════════════════════════════════════════════════
Admin-only endpoint that aggregates platform statistics via DashboardService.

Security: Admin-only (require_admin dependency).
"""
import logging
from typing import Dict

from fastapi import APIRouter, Depends, Request

from api.middleware.auth import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/dashboard", tags=["Admin Dashboard"])


def _get_dashboard_service(request: Request):
    return request.app.state.dashboard_service


@router.get("/stats", summary="Aggregated admin dashboard statistics")
async def dashboard_stats(request: Request, current_user: Dict = Depends(require_admin)):
    svc = _get_dashboard_service(request)
    return await svc.get_stats()
