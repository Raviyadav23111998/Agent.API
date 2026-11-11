"""
Bot Admin Service
════════════════════════════════════════════════════
"""
import logging
from typing import List, Dict, Optional

from api.repositories.bot_admin_repo import BotAdminRepository
from api.schemas.bot_admin import (
    BotCreateRequest, BotUpdateRequest, BotDTO, BotCreateResponseDTO,
    BotRuleDTO
)
from api.services.bot_service import _bot_session_pool

logger = logging.getLogger(__name__)

class BotAdminService:
    def __init__(self, bot_admin_repo: BotAdminRepository):
        self._repo = bot_admin_repo

    async def create_bot(self, data: BotCreateRequest, user_id: int) -> BotCreateResponseDTO:
        row = self._repo.create_bot(data, user_id)
        return BotCreateResponseDTO.model_validate(row)

    async def update_bot(self, bot_id: int, data: BotUpdateRequest, user_id: int) -> Optional[BotDTO]:
        row = self._repo.update_bot(bot_id, data, user_id)
        if not row:
            return None
        await _bot_session_pool.invalidate_bot(bot_id)
        return BotDTO.from_row(row)

    async def list_bots(self, user_id: int) -> List[BotDTO]:
        rows = self._repo.list_bots(user_id)
        return [BotDTO.from_row(r) for r in rows]

    async def get_bot(self, bot_id: int, user_id: int) -> Optional[BotDTO]:
        row = self._repo.get_bot(bot_id, user_id)
        if not row:
            return None
        return BotDTO.from_row(row)

    async def delete_bot(self, bot_id: int, user_id: int):
        self._repo.delete_bot(bot_id, user_id)

    async def get_bot_rules(self, bot_id: int, user_id: int) -> List[BotRuleDTO]:
        rows = self._repo.get_rules(bot_id, user_id)
        return [BotRuleDTO.model_validate(r) for r in rows]

    async def set_bot_rules(self, bot_id: int, user_id: int, rules: List[Dict]):
        self._repo.set_rules(bot_id, user_id, rules)
        await _bot_session_pool.invalidate_bot(bot_id)


