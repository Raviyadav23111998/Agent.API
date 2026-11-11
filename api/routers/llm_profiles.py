"""
Admin — LLM model profiles, budgets, and usage (V035).

Profiles: named complete model identities (provider+model+url+key+params).
Bind an application or user to a profile ("App A runs DeepSeek, App B runs
GLM"). Budgets: Claude-style per-user/app/tenant token+USD caps per window.
Usage: the ledger behind the caps and the admin Usage dashboard.
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from api.middleware.auth import get_current_user
from api.repositories.llm_profile_repo import LLMProfileRepository
from api.routers.llm_config import _is_admin, mask_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin", tags=["LLM Profiles"])


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              protected_namespaces=())


class ProfileRequest(_Camel):
    name: str
    provider: str
    model: str
    base_url: str
    api_key: Optional[str] = ""
    small_model: Optional[str] = None
    fallback_model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    reasoning_effort: Optional[str] = None
    is_active: Optional[bool] = None


class BindRequest(_Camel):
    scope: str = Field(..., description="app | user")
    scope_id: int
    profile_id: Optional[int] = Field(None, description="null = inherit")


class BudgetRequest(_Camel):
    scope_type: str = Field(..., description="user | app | tenant")
    scope_id: Optional[int] = None
    win: str = Field("day", description="day | week | month")
    max_tokens: int = 0
    max_usd: float = 0
    action: str = Field("block", description="block | warn")


def _repo(request: Request) -> LLMProfileRepository:
    return LLMProfileRepository(request.app.state.db)


def _require_admin(current_user: Dict):
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")


def _masked(p: Dict) -> Dict:
    p = dict(p)
    key = p.get("api_key") or ""
    p["api_key"] = "" if key.startswith("__config:") else mask_secret(key)
    return p


def _invalidate(profile_id: int = None):
    """Bust cached clients on this worker + rebuild sessions everywhere."""
    try:
        from client.cli import invalidate_profile_clients
        invalidate_profile_clients(profile_id)
    except Exception:
        pass
    try:
        from api.services.chat_service import invalidate_config
        invalidate_config()  # flush-all: profile bindings cross app scopes
    except Exception as e:
        logger.debug("profile invalidation broadcast failed: %s", e)


# ── Profiles ─────────────────────────────────────────────────────────────
@router.get("/llm-profiles")
async def list_profiles(request: Request,
                        current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    return [_masked(p) for p in _repo(request).list_profiles(include_inactive=True)]


@router.post("/llm-profiles")
async def create_profile(body: ProfileRequest, request: Request,
                         current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        row = _repo(request).create_profile(
            body.dict(), created_by=int(current_user.get("user_ID", 0)))
    except Exception as e:
        if "llm_profiles_name_uniq" in str(e):
            raise HTTPException(status_code=409,
                                detail=f"A profile named '{body.name}' already exists")
        raise
    _invalidate()
    return _masked(row)


@router.put("/llm-profiles/{profile_id}")
async def update_profile(profile_id: int, body: ProfileRequest, request: Request,
                         current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    try:
        row = _repo(request).update_profile(profile_id, body.dict(exclude_unset=True))
    except Exception as e:
        if "llm_profiles_name_uniq" in str(e):
            raise HTTPException(status_code=409,
                                detail=f"A profile named '{body.name}' already exists")
        raise
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    _invalidate(profile_id)
    return _masked(row)


@router.delete("/llm-profiles/{profile_id}")
async def delete_profile(profile_id: int, request: Request,
                         current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    if not _repo(request).delete_profile(profile_id):
        raise HTTPException(
            status_code=400,
            detail="Profile not found or is the default (undeletable)")
    _invalidate(profile_id)
    return {"message": "Profile deleted"}


@router.post("/llm-profiles/bind")
async def bind_profile(body: BindRequest, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    repo = _repo(request)
    if body.profile_id is not None and not repo.get_profile(body.profile_id):
        raise HTTPException(status_code=404, detail="Profile not found")
    if body.scope == "app":
        repo.bind_app(body.scope_id, body.profile_id)
    elif body.scope == "user":
        repo.bind_user(body.scope_id, body.profile_id)
    else:
        raise HTTPException(status_code=422, detail="scope must be app|user")
    _invalidate()
    return {"message": f"{body.scope} {body.scope_id} → profile {body.profile_id}"}


# ── Budgets ──────────────────────────────────────────────────────────────
@router.get("/budgets")
async def list_budgets(request: Request,
                       current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    return _repo(request).list_budgets()


@router.post("/budgets")
async def upsert_budget(body: BudgetRequest, request: Request,
                        current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    if body.scope_type not in ("user", "app", "tenant"):
        raise HTTPException(status_code=422, detail="scope_type must be user|app|tenant")
    if body.scope_type != "tenant" and body.scope_id is None:
        raise HTTPException(status_code=422, detail="scope_id required for user/app")
    # Validate against the DB CHECK constraints up front — a bad value would
    # otherwise surface as an opaque 500.
    if body.win not in ("day", "week", "month"):
        raise HTTPException(status_code=422, detail="win must be day|week|month")
    if body.action not in ("block", "warn"):
        raise HTTPException(status_code=422, detail="action must be block|warn")
    return _repo(request).upsert_budget(
        body.dict(), created_by=int(current_user.get("user_ID", 0)))


@router.delete("/budgets/{budget_id}")
async def delete_budget(budget_id: int, request: Request,
                        current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    if not _repo(request).delete_budget(budget_id):
        raise HTTPException(status_code=404, detail="Budget not found")
    return {"message": "Budget deleted"}


# ── Usage ────────────────────────────────────────────────────────────────
@router.get("/usage")
async def usage_summary(
    request: Request,
    group_by: str = Query("user", pattern="^(user|app|model|day)$"),
    days: int = Query(30, ge=1, le=365),
    current_user: Dict = Depends(get_current_user),
):
    _require_admin(current_user)
    return _repo(request).usage_summary(group_by=group_by, days=days)
