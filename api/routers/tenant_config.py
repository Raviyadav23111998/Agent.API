"""
TenantConfig Router — public, pre-login tenant branding (Multi-Tenancy Phase 1)
================================================================================
Implements GET /TenantConfig?subdomain=<label> which the Angular frontend
already calls on load (services/tenant-config.service.ts):

    host = window.location.hostname
    subdomain = host.split('.')[0]
    GET {api}/TenantConfig?subdomain={subdomain}

Resolution: subdomain/domain → MSystemRouter → tenant identity + tenant_profile
branding. PUBLIC (no auth — this drives the login screen). Always returns 200;
on miss it returns defaults so the frontend falls back to neutral branding.

See MULTITENANT_MASTER_PLAN.md §4 (N7).
"""

import logging
import os
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from api.middleware.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["TenantConfig"])


# ── Standalone logo (no MSystem master) ─────────────────────────────────────
# One logo per deployment, kept under the agent's own media root. With MSystem
# configured, branding still comes from tenant_profile (see tenant_config below).
# SVG is refused: served same-origin it could carry script.
_LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg",
               "image/webp": "webp", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico"}
_LOGO_MAX_BYTES = 2 * 1024 * 1024


def _branding_dir() -> str:
    from core.config import app_config
    base = app_config.get("media.base_path", "/var/agent-media/") or "/var/agent-media/"
    return os.path.join(base, "branding")


def _logo_path() -> Optional[str]:
    d = _branding_dir()
    for ext in set(_LOGO_TYPES.values()):
        p = os.path.join(d, f"logo.{ext}")
        if os.path.isfile(p):
            return p
    return None


def _defaults(subdomain: str) -> dict:
    return {
        "orgName": "Storeglance",
        "logoUrl": "TenantLogo" if _logo_path() else "",
        "email": "",
        "phone": "",
        "website": "",
        "address": "",
        "timezone": "",
        "themeColor": "#1976d2",
        "tenantStatus": "unknown",
        "subdomain": subdomain or "",
    }


@router.get("/TenantConfig", summary="Public tenant branding by subdomain/domain")
async def tenant_config(request: Request,
                        subdomain: str = Query("", description="Subdomain label or full host")):
    router_obj = getattr(request.app.state, "msystem_router", None)
    identifier = (subdomain
                  or request.headers.get("x-tenant-domain")
                  or request.headers.get("x-forwarded-host")
                  or request.headers.get("host", ""))

    if not router_obj or not identifier:
        return _defaults(subdomain)

    try:
        identity = router_obj.resolve(identifier)
    except Exception as e:
        logger.warning("tenant_config.resolve_failed: %s", e)
        return _defaults(subdomain)

    if not identity:
        return _defaults(subdomain)

    branding = {}
    try:
        branding = router_obj.get_branding(identity.tenant_id)
    except Exception as e:
        logger.warning("tenant_config.branding_failed: %s", e)

    addr = " ".join(
        x for x in [branding.get("address_line1"), branding.get("city"), branding.get("state")] if x
    ).strip()

    from core.tenant_branding import master_logo_url, gateway_base_from_request
    logo_url = master_logo_url(identifier,
                               has_logo=bool(branding.get("logo_url")),
                               gateway_base=gateway_base_from_request(request))

    return {
        "orgName": branding.get("org_name") or identity.display_name,
        "logoUrl": logo_url,
        "coverImageUrl": branding.get("cover_image_url") or "",
        "motto": branding.get("motto") or "",
        "email": branding.get("email") or "",
        "phone": branding.get("phone") or "",
        "website": branding.get("website") or "",
        "address": addr,
        "timezone": branding.get("timezone") or "",
        "themeColor": branding.get("theme_color") or "#1976d2",
        "tenantStatus": "active" if identity.is_active else "suspended",
        "tenantKey": identity.tenant_key,
        "subdomain": subdomain or identity.matched_domain or "",
    }


@router.get("/TenantLogo", summary="The deployment's logo (public)")
async def tenant_logo(domain: str = Query("", description="Ignored when standalone")):
    p = _logo_path()
    if not p:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    return FileResponse(p, headers={"Cache-Control": "public, max-age=300"})


@router.post("/TenantLogo", summary="Upload the deployment's logo (admin)")
async def upload_tenant_logo(file: UploadFile = File(...),
                             current_user: Dict = Depends(require_admin)):
    ext = _LOGO_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=400, detail="Logo must be PNG, JPEG, WebP or ICO")
    data = await file.read(_LOGO_MAX_BYTES + 1)
    if len(data) > _LOGO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Logo must be 2 MB or smaller")
    d = _branding_dir()
    os.makedirs(d, exist_ok=True)
    for old in set(_LOGO_TYPES.values()):
        try:
            os.remove(os.path.join(d, f"logo.{old}"))
        except FileNotFoundError:
            pass
    tmp = os.path.join(d, f".logo.{ext}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, os.path.join(d, f"logo.{ext}"))
    logger.info("tenant_logo.uploaded: %s bytes=%d by=%s", ext, len(data), current_user.get("user_code"))
    return {"success": True, "message": "Logo updated"}
