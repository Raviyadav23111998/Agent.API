"""
Channels → Visual Studio: status + direct .vsix download.
═══════════════════════════════════════════════════════════════════════════════
  GET /v1/channels/visualstudio/status    → availability, version, marketplace URL
  GET /v1/channels/visualstudio/download   → streams the packaged extension (.vsix)

Mirrors the VS Code channel (vscode_app.py). The download is auto-resolved per
tenant: the served .vsix has agent.tenant.json rewritten with this tenant's
domain + env gateway, so the install is pre-pointed (no manual setup).
"""
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.middleware.auth import require_admin
from api.services import visualstudio_app_service as vss

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/channels/visualstudio", tags=["Channels"])


def _tenant_domain(request: Request) -> str:
    return (request.headers.get("x-tenant-domain") or "").split(":")[0].strip().lower()


def _api_url(request: Request) -> str:
    """Derive the gateway /api/agent base for this env from the incoming request
    host (uat/sit/prod), so the prefilled extension targets the right gateway —
    identical to vscode_app._api_url."""
    host = (request.headers.get("x-forwarded-host")
            or request.headers.get("host") or "").split(":")[0].lower()
    if host.startswith("uat-") or ".uat" in host or host.startswith("uat"):
        return "https://uat-api.storeglance.com/api/agent"
    if host.startswith("sit-") or ".sit" in host or host.startswith("sit"):
        return "https://sit-api.storeglance.com/api/agent"
    return "https://api.storeglance.com/api/agent"


@router.get("/status")
async def visualstudio_status(request: Request, current_user: dict = Depends(require_admin)):
    path, filename = vss.find_latest_vsix()
    return {
        "available": bool(path),
        "version": vss.parse_version(filename),
        "filename": filename or "",
        "marketplaceUrl": vss.MARKETPLACE_URL,
        "tenantDomain": _tenant_domain(request),
    }


@router.get("/download")
async def visualstudio_download(request: Request, current_user: dict = Depends(require_admin)):
    path, filename = vss.find_latest_vsix()
    if not path:
        raise HTTPException(
            status_code=404,
            detail="Visual Studio extension package is not available on the server yet.")

    domain = _tenant_domain(request)
    vsix_bytes = vss.build_tenant_vsix(path, tenant_domain=domain, api_url=_api_url(request))

    return StreamingResponse(
        io.BytesIO(vsix_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
