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
from fastapi import APIRouter, Request, Query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["TenantConfig"])


def _defaults(subdomain: str) -> dict:
    return {
        "orgName": "Agent",
        "logoUrl": "",
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
