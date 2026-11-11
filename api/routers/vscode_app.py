"""
Channels → VS Code: status + direct .vsix download.
═══════════════════════════════════════════════════════════════════════════════
  GET /v1/channels/vscode/status    → availability, version, marketplace URL
  GET /v1/channels/vscode/download  → streams the packaged extension (.vsix)

Mirrors the Teams channel (teams_app.py). The extension is tenant-agnostic; the
tenant is set client-side via the `agent.tenantDomain` VS Code setting.
"""
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.middleware.auth import require_admin
from api.services import vscode_app_service as vas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/channels/vscode", tags=["Channels"])


def _tenant_domain(request: Request) -> str:
    return (request.headers.get("x-tenant-domain") or "").split(":")[0].strip().lower()


def _api_url(request: Request) -> str:
    """Derive the gateway /api/agent base for this env from the incoming request
    host (uat/sit/prod) so the prefilled extension targets the right gateway."""
    host = (request.headers.get("x-forwarded-host")
            or request.headers.get("host") or "").split(":")[0].lower()
    if host.startswith("uat-") or ".uat" in host or host.startswith("uat"):
        return "https://uat-ai.storeglance.com/api"
    if host.startswith("sit-") or ".sit" in host or host.startswith("sit"):
        return "https://sit-ai.storeglance.com/api"
    return "https://ai.storeglance.com/api"


@router.get("/status")
async def vscode_status(request: Request, current_user: dict = Depends(require_admin)):
    path, filename = vas.find_latest_vsix()
    return {
        "available": bool(path),
        "version": vas.parse_version(filename),
        "filename": filename or "",
        "marketplaceUrl": vas.MARKETPLACE_URL,
        "tenantDomain": _tenant_domain(request),
    }


@router.get("/download")
async def vscode_download(request: Request, current_user: dict = Depends(require_admin)):
    path, filename = vas.find_latest_vsix()
    if not path:
        raise HTTPException(
            status_code=404,
            detail="VS Code extension package is not available on the server yet.")

    domain = _tenant_domain(request)
    vsix_bytes = vas.build_tenant_vsix(path, tenant_domain=domain, api_url=_api_url(request))

    return StreamingResponse(
        io.BytesIO(vsix_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
