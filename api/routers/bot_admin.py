"""
Bot Admin Router — REST endpoints for managing bots.
════════════════════════════════════════════════════
"""
import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import require_admin
from api.schemas.bot_admin import (
    BotCreateRequest, BotUpdateRequest, BotDTO, BotCreateResponseDTO,
    BotRuleDTO, BotRuleCreateRequest
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/bots", tags=["Bot Admin"])

def _get_bot_admin_service(request: Request):
    return request.app.state.bot_admin_service

@router.get("", response_model=List[BotDTO], summary="List bots")
async def list_bots(request: Request, current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    return await svc.list_bots(user_id=uid)

@router.post("", response_model=BotCreateResponseDTO, summary="Create a bot")
async def create_bot(req: BotCreateRequest, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    return await svc.create_bot(req, user_id=uid)

@router.get("/{bot_id}", response_model=BotDTO, summary="Get bot details")
async def get_bot(bot_id: int, request: Request,
                  current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    bot = await svc.get_bot(bot_id, user_id=uid)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot

@router.put("/{bot_id}", response_model=BotDTO, summary="Update bot")
async def update_bot(bot_id: int, req: BotUpdateRequest, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    bot = await svc.update_bot(bot_id, req, user_id=uid)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot

@router.delete("/{bot_id}", summary="Delete bot")
async def delete_bot(bot_id: int, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    await svc.delete_bot(bot_id, user_id=uid)
    return {"message": "Bot deleted"}


@router.get("/{bot_id}/rules", response_model=List[BotRuleDTO])
async def get_bot_rules(bot_id: int, request: Request,
                        current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    return await svc.get_bot_rules(bot_id, user_id=uid)

@router.post("/{bot_id}/rules")
async def set_bot_rules(bot_id: int, rules: List[BotRuleCreateRequest], request: Request,
                        current_user: Dict = Depends(require_admin)):
    svc = _get_bot_admin_service(request)
    uid = int(current_user.get("user_ID", 0))
    try:
        await svc.set_bot_rules(bot_id, user_id=uid, rules=[r.model_dump() for r in rules])
        return {"message": "Rules updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


