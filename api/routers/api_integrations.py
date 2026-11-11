"""
API Integrations admin surface — onboard any HTTP API as governed agent tools.
═══════════════════════════════════════════════════════════════════════════════
Org-admin only. Mirrors the Connections router (auth dep, app.state.db,
_hot_apply after mutations). Tenant-routed: every call uses request.app.state.db
(the TenantDBProxy), so an integration lands in the admin's OWN tenant DB.

  GET    /v1/api-integrations                       list the catalog
  POST   /v1/api-integrations/import                {slug, source|spec, allow_private?, display_name?}
  GET    /v1/api-integrations/{id}                  detail + operations
  PATCH  /v1/api-integrations/{id}                  {status?, egress_allow?, allow_private?}
  PATCH  /v1/api-integrations/{id}/ops/{op_id}      {enabled?, side_effect?, requires_approval?, embed_safe?}
  POST   /v1/api-integrations/{id}/reimport         re-fetch the stored spec + diff
  POST   /v1/api-integrations/{id}/test             generic 'Test connection' probe
  DELETE /v1/api-integrations/{id}
  GET    /v1/api-integrations/{id}/grants
  POST   /v1/api-integrations/{id}/grants           {scope, ref?, op_filter?}
  DELETE /v1/api-integrations/{id}/grants/{grant_id}

NOTE: the prefix is `/v1/api-integrations`, NOT `/v1/integrations` — the latter is
already owned by the embeddable-bot platform router (api/routers/integrations.py,
the ag_bot.bots "integration"). Sharing the prefix shadowed the embed-bot
list/patch endpoints (this router is registered first in main.py). The schema
(`ag_api`) was disambiguated for the same reason; the HTTP surface must match.

After every mutation _hot_apply() flushes sessions + busts the dynamic catalog
cache (no restart). All paths are inert unless `agent.dynamic_integrations` is on.
See API_INTEGRATION_IMPLEMENTATION_PLAN.md §6.
"""

import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from api.middleware.auth import get_current_user
from core.connections import Connections

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/api-integrations", tags=["API Integrations"])


def _db(request: Request):
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(503, "Database not available.")
    return db


def _connections(request: Request) -> Connections:
    c = getattr(request.app.state, "connections", None)
    if c is None:
        c = Connections(_db(request))
        request.app.state.connections = c
    return c


def _store(request: Request):
    from core.integrations.store import IntegrationStore
    return IntegrationStore(_db(request))


def _embeddings(request: Request):
    """The shared EmbeddingClient off the AgentCLI (best-effort; None degrades
    ingestion to keyword selection).

    The AgentCLI singleton is built lazily on the first chat, so right after a
    restart `_cli` is None and an import would silently skip embeddings (no vector
    tool-RAG until a later re-import). Fall back to a fresh EmbeddingClient, which
    resolves the tenant's llm.embedding_* config independently and is cheap.
    """
    svc = getattr(request.app.state, "agent_service", None)
    cli = getattr(svc, "_cli", None)
    emb = getattr(cli, "_embeddings", None)
    if emb is None:
        try:
            from core.embeddings import EmbeddingClient
            emb = EmbeddingClient()
        except Exception:
            emb = None
    return emb


def _is_admin(user: dict) -> bool:
    return (user.get("role", "member") or "").lower() in (
        "admin", "superadmin", "administrator", "owner", "tenant owner")


def _require_admin(user: dict):
    if not _is_admin(user):
        raise HTTPException(403, "Admin role required to manage API integrations.")


def _hot_apply():
    try:
        from api.services.chat_service import refresh_integrations_global
        refresh_integrations_global()
    except Exception as e:
        logger.warning("integrations hot-apply failed: %s", e)


class ImportSpec(BaseModel):
    slug: str
    source: Optional[str] = Field(None, description="URL, raw spec text, or mcp:// server URL")
    spec: Optional[Dict[str, Any]] = Field(None, description="already-parsed spec object")
    spec_kind: Optional[str] = Field(None, description="'openapi'|'swagger'|'mcp' (auto-detected if omitted)")
    display_name: Optional[str] = None
    allow_private: bool = False


class IntegrationPatch(BaseModel):
    status: Optional[str] = None
    egress_allow: Optional[List[str]] = None
    allow_private: Optional[bool] = None
    auth_type: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None
    default_headers: Optional[Dict[str, str]] = None


class OpPatch(BaseModel):
    enabled: Optional[bool] = None
    side_effect: Optional[str] = None
    requires_approval: Optional[bool] = None
    embed_safe: Optional[bool] = None


class GrantCreate(BaseModel):
    scope: str = Field(..., description="'app' | 'persona' | 'org'")
    ref: Optional[str] = Field(None, description="app_id | persona_id; omit for org")
    op_filter: Optional[List[str]] = None


@router.get("")
async def list_integrations(request: Request, current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    return await run_in_threadpool(_store(request).list_integrations)


@router.post("/import")
async def import_integration(body: ImportSpec, request: Request,
                             current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    source: Union[str, dict, None] = body.spec if body.spec is not None else body.source
    if source is None:
        raise HTTPException(400, "Provide either 'spec' (object) or 'source' (URL/text).")
    from core.integrations.ingest import SpecIngestor
    from core.integrations.openapi import SpecError

    def _run():
        ing = SpecIngestor(_db(request), _connections(request),
                           embeddings=_embeddings(request))
        return ing.ingest(source, slug=body.slug, spec_kind=body.spec_kind,
                          created_by=current_user.get("user_ID"),
                          allow_private=body.allow_private,
                          display_name=body.display_name)
    try:
        report = await run_in_threadpool(_run)
    except SpecError as e:
        raise HTTPException(400, f"Spec rejected: {e}")
    except Exception as e:
        logger.exception("integration import failed")
        raise HTTPException(400, f"Import failed: {e}")
    _hot_apply()
    return {
        "slug": report.slug, "integration_id": report.integration_id,
        "operation_count": report.operation_count, "added": report.added,
        "updated": report.updated, "deprecated": report.deprecated,
        "embedded": report.embedded, "unchanged": report.unchanged,
        "security_scheme": report.security_scheme, "auth_provider": report.auth_provider,
        "warnings": report.warnings,
    }


@router.get("/{integration_id}")
async def get_integration(integration_id: int, request: Request,
                          current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    store = _store(request)
    integ = await run_in_threadpool(store.get_integration, integration_id)
    if not integ:
        raise HTTPException(404, "Integration not found.")
    integ.pop("spec_raw", None)
    integ["operations"] = await run_in_threadpool(store.list_operations_display, integration_id)
    integ["grants"] = await run_in_threadpool(store.list_grants, integration_id)
    return integ


@router.patch("/{integration_id}")
async def patch_integration(integration_id: int, body: IntegrationPatch, request: Request,
                            current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    await run_in_threadpool(lambda: _store(request).update_integration(
        integration_id, status=body.status, egress_allow=body.egress_allow,
        allow_private=body.allow_private, auth_type=body.auth_type,
        auth_config=body.auth_config, default_headers=body.default_headers))
    _hot_apply()
    return {"ok": True}


@router.patch("/{integration_id}/ops/{operation_id}")
async def patch_operation(integration_id: int, operation_id: str, body: OpPatch,
                          request: Request, current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    await run_in_threadpool(lambda: _store(request).update_operation(
        integration_id, operation_id, enabled=body.enabled, side_effect=body.side_effect,
        requires_approval=body.requires_approval, embed_safe=body.embed_safe))
    _hot_apply()
    return {"ok": True}


@router.post("/{integration_id}/reimport")
async def reimport_integration(integration_id: int, request: Request, force: bool = False,
                               current_user: Dict = Depends(get_current_user)):
    """Re-derive ops from the stored spec. `?force=true` re-derives even when the
    spec is byte-identical — use it to apply normalizer upgrades or repair an
    integration without re-uploading. Admin per-op overrides are preserved."""
    _require_admin(current_user)
    store = _store(request)
    integ = await run_in_threadpool(store.get_integration, integration_id)
    if not integ or not integ.get("spec_raw"):
        raise HTTPException(404, "Integration or its stored spec not found.")
    from core.integrations.ingest import SpecIngestor

    def _run():
        ing = SpecIngestor(_db(request), _connections(request),
                           embeddings=_embeddings(request))
        return ing.ingest(integ["spec_raw"], slug=integ["slug"],
                          created_by=current_user.get("user_ID"),
                          allow_private=integ.get("allow_private", False),
                          source_url=integ.get("base_url"), force=force)
    report = await run_in_threadpool(_run)
    _hot_apply()
    return {"added": report.added, "updated": report.updated,
            "deprecated": report.deprecated, "unchanged": report.unchanged}


@router.post("/{integration_id}/embeddings/backfill")
async def backfill_embeddings(integration_id: int, request: Request,
                              current_user: Dict = Depends(get_current_user)):
    """Embed any operations still missing a vector (idempotent repair).

    A large import can exhaust its embedding time budget and leave some ops on
    keyword-only selection; this finishes the job without a full re-import.
    """
    _require_admin(current_user)
    store = _store(request)
    integ = await run_in_threadpool(store.get_integration, integration_id)
    if not integ:
        raise HTTPException(404, "Integration not found.")
    from core.integrations.ingest import SpecIngestor

    def _run():
        ing = SpecIngestor(_db(request), _connections(request),
                           embeddings=_embeddings(request))
        return ing.backfill_embeddings(integration_id)
    result = await run_in_threadpool(_run)
    _hot_apply()
    return result


@router.post("/{integration_id}/test")
async def test_integration(integration_id: int, request: Request,
                           current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    store = _store(request)
    integ = await run_in_threadpool(store.get_integration, integration_id)
    if not integ:
        raise HTTPException(404, "Integration not found.")
    provider = integ.get("auth_provider")
    if not provider:
        return {"ok": True, "message": "Public API (no credential to test)."}
    conns = _connections(request)

    def _run():
        cred = conns.resolve_or_none(provider, user_id=current_user.get("user_ID"))
        if cred is None:
            return False, f"No connection for '{provider}' — add one first."
        from core.integrations.runtime import verify_integration_credential
        return verify_integration_credential(provider, cred.config, cred.secret,
                                             connections=conns)
    ok, message = await run_in_threadpool(_run)
    return {"ok": ok, "message": message}


@router.delete("/{integration_id}")
async def delete_integration(integration_id: int, request: Request,
                             purge_credentials: bool = True,
                             current_user: Dict = Depends(get_current_user)):
    """Delete an integration. Operations + grants cascade (FK). By default the
    auto-created `api_{slug}` credential provider and its stored connections are
    also removed so nothing is orphaned; pass `?purge_credentials=false` to keep
    the credential (e.g. you plan to re-import the same API)."""
    _require_admin(current_user)
    store = _store(request)
    integ = await run_in_threadpool(store.get_integration, integration_id)
    if not integ:
        raise HTTPException(404, "Integration not found.")
    provider = integ.get("auth_provider")
    await run_in_threadpool(store.delete_integration, integration_id)
    if purge_credentials and provider and str(provider).startswith("api_"):
        try:
            await run_in_threadpool(_connections(request).delete_provider, provider)
        except Exception as e:
            logger.warning("integration delete: credential cleanup failed for %s: %s",
                           provider, e)
    _hot_apply()
    return {"ok": True, "credential_purged": bool(
        purge_credentials and provider and str(provider).startswith("api_"))}


@router.get("/{integration_id}/grants")
async def list_grants(integration_id: int, request: Request,
                      current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    return await run_in_threadpool(_store(request).list_grants, integration_id)


@router.post("/{integration_id}/grants")
async def add_grant(integration_id: int, body: GrantCreate, request: Request,
                    current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    if body.scope not in ("app", "persona", "org"):
        raise HTTPException(400, "scope must be app | persona | org.")
    ref = "" if body.scope == "org" else (body.ref or "")
    if body.scope != "org" and not ref:
        raise HTTPException(400, f"{body.scope} grants require a ref.")
    gid = await run_in_threadpool(lambda: _store(request).add_grant(
        integration_id, body.scope, ref, body.op_filter, current_user.get("user_ID")))
    _hot_apply()
    return {"grant_id": gid}


@router.delete("/{integration_id}/grants/{grant_id}")
async def delete_grant(integration_id: int, grant_id: int, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    await run_in_threadpool(_store(request).delete_grant, grant_id)
    _hot_apply()
    return {"ok": True}
