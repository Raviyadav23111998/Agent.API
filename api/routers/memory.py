"""
Memory Router — Persistent memory store + recall.
══════════════════════════════════════════════════
"""
import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, Request, Query

from api.middleware.auth import get_current_user
from api.schemas.memory import MemoryDTO, MemoryStoreRequest, MemoryRecallRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/memory", tags=["Memory"])


def _get_memory_repo(request: Request):
    return request.app.state.memory_repo


@router.post("/store", summary="Store a memory")
async def store_memory(req: MemoryStoreRequest, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    repo = _get_memory_repo(request)
    user_id = str(current_user.get("user_ID", "__cli__"))
    result = repo.store(
        user_id=user_id, key=req.key, value=req.value,
        category=req.category or 'fact', layer=req.layer,
    )
    return result


@router.post("/recall", summary="Search memories (FTS)")
async def recall_memory(req: MemoryRecallRequest, request: Request,
                        current_user: Dict = Depends(get_current_user)):
    repo = _get_memory_repo(request)
    user_id = str(current_user.get("user_ID", "__cli__"))
    return repo.recall(req.query, user_id=user_id,
                       category=req.category, limit=req.limit)


@router.get("", response_model=List[MemoryDTO], summary="List all memories")
async def list_memories(
    request: Request,
    category: str = Query(None),
    current_user: Dict = Depends(get_current_user),
):
    repo = _get_memory_repo(request)
    user_id = str(current_user.get("user_ID", "__cli__"))
    return repo.list_memories(user_id, category)


@router.delete("/{memory_id}", summary="Delete memory")
async def delete_memory(memory_id: int, request: Request,
                        current_user: Dict = Depends(get_current_user)):
    repo = _get_memory_repo(request)
    user_id = str(current_user.get("user_ID", "__cli__"))
    repo.delete_memory(memory_id, user_id=user_id)
    return {"message": "Memory deleted"}


@router.get("/stats", summary="Memory statistics")
async def stats(request: Request, current_user: Dict = Depends(get_current_user)):
    repo = _get_memory_repo(request)
    user_id = str(current_user.get("user_ID", "__cli__"))
    return repo.get_stats(user_id)
