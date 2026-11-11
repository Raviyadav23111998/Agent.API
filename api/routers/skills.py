"""
Admin — Skills & Learning (V036).

The skill library the agent maintains about itself: list/edit/pin/archive/
rollback, plus the effectiveness signals (use_count, correction_after_use)
the curator prioritizes by.
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from api.middleware.auth import get_current_user
from api.repositories.skill_repo import SkillRepository
from api.routers.llm_config import _is_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/skills", tags=["Skills"])


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              protected_namespaces=())


class SkillUpdate(_Camel):
    description: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[List[str]] = None
    pinned: Optional[bool] = None


def _repo(request: Request) -> SkillRepository:
    return SkillRepository(request.app.state.db)


def _require_admin(current_user: Dict):
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")


def _invalidate():
    try:
        from api.services.chat_service import invalidate_config
        invalidate_config()
    except Exception:
        pass


@router.get("")
async def list_skills(request: Request,
                      current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    return _repo(request).list_all(include_inactive=True)


@router.get("/{skill_id}/versions")
async def skill_versions(skill_id: int, request: Request,
                         current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    return _repo(request).versions(skill_id)


@router.put("/{skill_id}")
async def update_skill(skill_id: int, body: SkillUpdate, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    repo = _repo(request)
    uid = int(current_user.get("user_ID", 0))
    if body.pinned is not None:
        repo.set_pinned(skill_id, body.pinned)
    if body.body:
        # Full-body edit (also carries any description/tags change).
        repo.update_body(skill_id, body.body, append=False,
                         edited_by=f"user:{uid}",
                         description=body.description, tags=body.tags)
    elif body.description is not None or body.tags is not None:
        # Metadata-only edit — must NOT overwrite the body with "".
        repo.update_meta(skill_id, edited_by=f"user:{uid}",
                         description=body.description, tags=body.tags)
    _invalidate()
    return {"message": "Skill updated"}


@router.post("/{skill_id}/archive")
async def archive_skill(skill_id: int, request: Request,
                        current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    uid = int(current_user.get("user_ID", 0))
    if not _repo(request).archive(skill_id, edited_by=f"user:{uid}"):
        raise HTTPException(status_code=400,
                            detail="Skill is pinned or bundled — unpin first")
    _invalidate()
    return {"message": "Skill archived"}


@router.post("/{skill_id}/rollback/{version}")
async def rollback_skill(skill_id: int, version: int, request: Request,
                         current_user: Dict = Depends(get_current_user)):
    _require_admin(current_user)
    uid = int(current_user.get("user_ID", 0))
    if not _repo(request).restore_version(skill_id, version,
                                          edited_by=f"user:{uid}"):
        raise HTTPException(status_code=404, detail="Version not found")
    _invalidate()
    return {"message": f"Rolled back to v{version}"}
