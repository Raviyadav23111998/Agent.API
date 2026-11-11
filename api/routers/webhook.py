from fastapi import APIRouter, Request, Response
import json
import os
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["Webhook"])

_TEAMS_WORKER_PORT = os.environ.get("AG_TEAMS_WORKER_PORT", "8115")
TEAMS_INTERNAL_URL = f"http://127.0.0.1:{_TEAMS_WORKER_PORT}/api/webhook/teams"


def _extract_aad_tenant_id(activity: dict) -> str:
    """The Microsoft 365 / Azure AD tenant GUID carried on every Bot Framework
    activity (channelData.tenant.id). Identifies WHICH customer's Teams the
    message came from."""
    try:
        return (((activity or {}).get("channelData") or {}).get("tenant") or {}).get("id", "") or ""
    except Exception:
        return ""


def _resolve_tenant_domain(activity: dict, request: Request) -> str:
    """Map an inbound Teams activity → the Storeglance tenant DOMAIN, so we can inject
    it as X-Tenant-Domain and reuse the SAME header-based tenant resolution that
    web/VSCode use (a Teams webhook carries no host/subdomain of its own).

    Resolution order (first hit wins):
      0. ?tenant=<domain> on the messaging-endpoint URL. Each tenant runs their OWN
         Azure Bot (BYO M365 app) and sets its messaging endpoint to
         …/webhook/teams?tenant=<their-domain>, so the tenant is carried explicitly —
         the SAME pattern as the chatbot widget (?tenant=) and VS Code (tenantDomain).
         Zero-config, no global AAD registry. This is the primary path.
      1. AG_TEAMS_TENANT_MAP env — JSON {"<aad_tenant_guid>": "acme.storeglanceai.com"}.
      2. MSystemRouter hook (resolve_domain_by_aad_tenant), if available.
    Returns "" when unknown — the request is forwarded unchanged (default ctx).
    """
    try:
        q = (request.query_params.get("tenant") or "").strip()
        if q:
            return q
    except Exception:
        pass

    aad = _extract_aad_tenant_id(activity)
    if not aad:
        return ""

    raw = os.environ.get("AG_TEAMS_TENANT_MAP", "")
    if raw:
        try:
            dom = (json.loads(raw).get(aad) or "").strip()
            if dom:
                return dom
        except Exception as e:
            logger.warning("teams.tenant_map_parse_failed: %s", e)

    router_obj = getattr(request.app.state, "msystem_router", None)
    resolver = getattr(router_obj, "resolve_domain_by_aad_tenant", None) if router_obj else None
    if callable(resolver):
        try:
            dom = (resolver(aad) or "").strip()
            if dom:
                return dom
        except Exception as e:
            logger.warning("teams.aad_resolve_failed: %s", e)

    return ""


@router.post("/teams")
async def teams_webhook(request: Request):
    """
    Receive Microsoft Teams webhooks and forward them to the GatewayRunner's internal port.

    A Teams activity has no host/subdomain that identifies the tenant (unlike a
    browser hitting {tenant}.storeglanceai.com). So here we MANIPULATE the request:
    derive the tenant's domain from the activity and inject it as X-Tenant-Domain
    before forwarding — making Teams use the exact same header-based tenant
    resolution as web/VSCode, with no special-casing downstream.
    """
    try:
        body = await request.body()
        headers = dict(request.headers)

        headers.pop("host", None)
        headers.pop("content-length", None)

        try:
            activity = json.loads(body) if body else {}
        except Exception:
            activity = {}
        tenant_domain = _resolve_tenant_domain(activity, request)
        if tenant_domain:
            headers["x-tenant-domain"] = tenant_domain
            logger.info("[Teams Webhook] injected X-Tenant-Domain=%s (aad=%s)",
                        tenant_domain, _extract_aad_tenant_id(activity)[:8])
        else:
            logger.info("[Teams Webhook] no tenant domain resolved (aad=%s) — default context",
                        _extract_aad_tenant_id(activity)[:8] or "?")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                TEAMS_INTERNAL_URL,
                content=body,
                headers=headers,
                timeout=10.0,
            )

        return Response(content=response.content, status_code=response.status_code,
                        media_type=response.headers.get("Content-Type"))

    except httpx.ConnectError:
        logger.error("[Teams Webhook] Internal Gateway worker not running on port %s.", _TEAMS_WORKER_PORT)
        return Response(content="Gateway worker unavailable", status_code=503)
    except Exception as e:
        logger.error("[Teams Webhook] Error forwarding webhook: %s", e)
        return Response(content="Internal Server Error", status_code=500)
