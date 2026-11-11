"""
Brain Router — Knowledge base search + document management.
═══════════════════════════════════════════════════════════

SECURITY: Every endpoint scopes data by owner_id + app_id from the caller.
  - Reads: user sees own docs + __tenant__ docs, WITHIN their app_id
  - Writes (ingest): defaults to __tenant__ for org-wide visibility within app
  - Deletes: only allowed on docs owned by user or __tenant__, within app
  - 403 if the caller has no app_id (old token — user must re-login)

CALLERS: search, ingest and stats accept EITHER a signed-in human (JWT) or a
backend (X-API-Key). A product keeping this knowledge base in step with its own
content has no login and no refresh cycle, and its only alternative was writing
to ag_brain.documents directly — around the API, past every rule enforced here.

A service key must still carry the capability:

    brain:read    search, stats
    brain:write   ingest

deliberately NOT the `chat` scope an existing key already holds. Answering
questions from the knowledge base and deciding what is in it are different
powers, and a key minted for the first must not silently acquire the second.

Deletion stays JWT-only. A backend that can write can already correct itself by
re-ingesting the same source_path; erasing a corpus is a human act, and leaving
it out means a leaked backend key cannot empty the base.
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.middleware.api_key_auth import is_service, require_scope, require_user_or_service
from api.middleware.auth import get_current_user
from api.schemas.brain import DocumentDTO, SearchRequest, SearchResult, IngestRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/brain", tags=["Brain"])


def _get_brain_repo(request: Request):
    return request.app.state.brain_repo


def _resolve_owner_id(current_user: Dict) -> str:
    """Extract owner_id from JWT claims for row-level access control."""
    return str(current_user.get("user_ID", "__tenant__"))


def _is_admin(current_user: Dict) -> bool:
    """Check if user has admin role (can view all apps).

    A service principal carries role="service", which is deliberately absent
    from this list: an app-scoped credential must never reach the cross-app
    override below, whatever appId it passes.
    """
    role = str(current_user.get("role", "")).lower()
    return role in ("admin", "superadmin", "super_admin", "administrator", "owner", "tenant owner")


def _require(principal: Dict, scope: str) -> None:
    """Assert a capability, for a service caller only.

    A JWT's authority comes from its role and its app_id, which the helpers
    above already apply. Scopes are a property of a KEY, so asking a human
    principal for one would refuse every signed-in user of these endpoints.
    """
    if is_service(principal):
        require_scope(principal, scope)


def _resolve_app_id(current_user: Dict, override: Optional[int] = None) -> Optional[int]:
    """Extract app_id from JWT. Strict enforcement for regular users.

    Admin override rules:
      - appId=0 query param → None (all apps, admin only)
      - appId=N query param → N (specific app filter)
      - No override          → JWT app_id (default scope)

    Regular users: always scoped to JWT app_id, override ignored.
    """
    if override is not None:
        if override == 0 and _is_admin(current_user):
            return None
        if _is_admin(current_user):
            return override

    jwt_app_id = current_user.get("app_id")
    if jwt_app_id is None:
        if _is_admin(current_user):
            return None
        # Same refusal either way — fail closed — but a backend has no login to
        # repeat, so telling it to re-log-in would send whoever is holding the
        # failure to the one place that cannot help them.
        if is_service(current_user):
            raise HTTPException(
                status_code=403,
                detail="This API key is not bound to an application.",
            )
        raise HTTPException(status_code=403, detail="Token missing app_id — please re-login.")
    return int(jwt_app_id)


@router.post("/search", response_model=List[SearchResult], response_model_by_alias=True, summary="Search knowledge base")
async def search(req: SearchRequest, request: Request,
                 current_user: Dict = Depends(require_user_or_service),
                 app_id: Optional[int] = Query(None, alias="appId")):
    _require(current_user, "brain:read")
    repo = _get_brain_repo(request)
    owner_id = _resolve_owner_id(current_user)
    effective_app_id = _resolve_app_id(current_user, app_id)
    return repo.search(req.query, owner_id=owner_id, doc_type=req.doc_type, limit=req.limit, app_id=effective_app_id)


@router.get("/documents", response_model=List[DocumentDTO], response_model_by_alias=True, summary="List documents")
async def list_documents(request: Request,
                         current_user: Dict = Depends(get_current_user),
                         app_id: Optional[int] = Query(None, alias="appId")):
    repo = _get_brain_repo(request)
    owner_id = _resolve_owner_id(current_user)
    effective_app_id = _resolve_app_id(current_user, app_id)
    return repo.list_documents(owner_id=owner_id, app_id=effective_app_id)


@router.get("/documents/{doc_id}", response_model=DocumentDTO, response_model_by_alias=True, summary="Get document")
async def get_document(doc_id: int, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    repo = _get_brain_repo(request)
    owner_id = _resolve_owner_id(current_user)
    doc = repo.get_document(doc_id, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/ingest", summary="Ingest document into knowledge base")
async def ingest(req: IngestRequest, request: Request,
                 current_user: Dict = Depends(require_user_or_service)):
    _require(current_user, "brain:write")
    repo = _get_brain_repo(request)
    uid = int(current_user.get("user_ID", 0) or 0)
    effective_app_id = _resolve_app_id(current_user, req.app_id)
    result = repo.ingest_document(
        source_path=req.source_path, content=req.content,
        title=req.title or '', doc_type=req.doc_type,
        owner_id='__tenant__', created_by=uid,
        app_id=effective_app_id,
    )
    return result


@router.delete("/documents/{doc_id}", summary="Delete document")
async def delete_document(doc_id: int, request: Request,
                          current_user: Dict = Depends(get_current_user)):
    """Delete a document. Signed-in humans only — see the module docstring.

    The app scope is applied HERE and was not before. This module's contract has
    always read "Deletes: only allowed on docs owned by user or __tenant__,
    WITHIN app", but the repository filtered on owner_id alone. Since ingested
    documents are owned by '__tenant__' by design, every one of them was
    deletable by any signed-in user of any OTHER application in the tenant.

    An admin stays UNSCOPED, and that is deliberate rather than lax. Reads
    already let an admin cross apps (`?appId=0`), and deletion is reached from
    the same console; scoping them to their own app_id here would close the hole
    by breaking the console that manages other applications' documents. The gap
    was regular users, so that is what this narrows — no existing admin flow
    changes behaviour.
    """
    repo = _get_brain_repo(request)
    owner_id = _resolve_owner_id(current_user)
    effective_app_id = None if _is_admin(current_user) else _resolve_app_id(current_user)
    repo.delete_document(doc_id, owner_id=owner_id, app_id=effective_app_id)
    return {"message": "Document deleted"}


@router.get("/stats", summary="Knowledge base statistics")
async def stats(request: Request, current_user: Dict = Depends(require_user_or_service),
               app_id: Optional[int] = Query(None, alias="appId")):
    _require(current_user, "brain:read")
    repo = _get_brain_repo(request)
    owner_id = _resolve_owner_id(current_user)
    effective_app_id = _resolve_app_id(current_user, app_id)
    return repo.get_stats(owner_id=owner_id, app_id=effective_app_id)


@router.get("/health", summary="Live knowledge-base health check")
async def health(request: Request, current_user: Dict = Depends(get_current_user)):
    """REAL health check for the tenant's knowledge base.

    Actively probes every store — pings Elasticsearch, runs a Cypher against
    Neo4j (a bad/empty credential shows here, not silently), makes a live
    embedding call — and reports per-pillar reachability + indexing coverage
    from the reconciliation state. Returns HTTP 503 when any configured pillar
    is unhealthy so uptime monitors and the admin UI see the truth, not a
    rubber-stamp 200.
    """
    import asyncio
    from fastapi.responses import JSONResponse
    from core.tenant_context import current_tenant
    from core.tenant_resolver import get_global_resolver

    resolver = get_global_resolver()
    try:
        storage = (resolver.for_tenant(current_tenant()).storage_manager
                   if resolver is not None else None)
    except Exception as e:
        storage = None
        err = str(e)
    if storage is None or not hasattr(storage, "health_probe"):
        return JSONResponse(status_code=503, content={
            "status": "unhealthy",
            "error": "brain storage unavailable for this tenant",
        })
    report = await asyncio.to_thread(storage.health_probe)
    code = 503 if report.get("status") == "unhealthy" else 200
    return JSONResponse(status_code=code, content=report)


