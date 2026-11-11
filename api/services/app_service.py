"""
Application Service — Business logic for Application management.
"""
import logging
from typing import List, Dict, Any, Optional

from api.repositories.app_repo import AppRepository
from api.repositories.persona_repo import PersonaRepository
from api.schemas.app_admin import ApplicationCreateRequest, ApplicationUpdateRequest, PersonaCreateRequest, PersonaUpdateRequest

logger = logging.getLogger(__name__)

VALID_APP_TYPES = {'internal', 'chatbot', 'api', 'mobile', 'widget'}


def _invalidate_sessions(persona_id: int = None, app_id: int = None,
                         integration_id: int = None):
    """Clear stale agent sessions (local + all workers) after a config write.

    Lazy import keeps app_service free of a hard chat_service dependency, and
    a failure here must never break the admin write — invalidation is
    best-effort (worst case: config applies on the next TTL expiry).
    """
    try:
        from api.services.chat_service import invalidate_config
        invalidate_config(persona_id=persona_id, app_id=app_id,
                          integration_id=integration_id)
    except Exception as e:
        logger.warning("session invalidation failed: %s", e)


class AppService:
    """Service layer for Application CRUD."""

    def __init__(self, repo: AppRepository, persona_repo: PersonaRepository = None):
        self._repo = repo
        self._persona_repo = persona_repo

    async def list_apps(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        return self._repo.list_apps(include_inactive=include_inactive)

    async def get_app(self, app_id: int) -> Optional[Dict[str, Any]]:
        return self._repo.get_app(app_id)

    async def create_app(self, req: ApplicationCreateRequest, user_id: int = None) -> Dict[str, Any]:
        if req.app_type not in VALID_APP_TYPES:
            raise ValueError(f"Invalid app_type '{req.app_type}'. Must be one of: {VALID_APP_TYPES}")
        return self._repo.create_app(
            name=req.name,
            description=req.description,
            app_type=req.app_type,
            llm_model=req.llm_model,
            max_tokens_day=req.max_tokens_day,
            max_documents=req.max_documents,
            created_by=user_id,
        )

    async def update_app(self, app_id: int, req: ApplicationUpdateRequest) -> Optional[Dict[str, Any]]:
        update_data = req.model_dump(exclude_none=True)
        if 'app_type' in update_data and update_data['app_type'] not in VALID_APP_TYPES:
            raise ValueError(f"Invalid app_type. Must be one of: {VALID_APP_TYPES}")
        result = self._repo.update_app(app_id, **update_data)
        _invalidate_sessions(app_id=app_id)
        return result

    async def delete_app(self, app_id: int) -> bool:
        return self._repo.delete_app(app_id)


    def list_app_personas(self, app_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
        if not self._persona_repo:
            raise ValueError("PersonaRepository not initialized.")
        return self._persona_repo.list_personas(app_id=app_id, include_inactive=include_inactive)

    def create_app_persona(self, app_id: int, req: PersonaCreateRequest) -> Dict[str, Any]:
        if not self._persona_repo:
            raise ValueError("PersonaRepository not initialized.")
        result = self._persona_repo.create_persona(
            app_id=app_id,
            name=req.name,
            identity_prompt=req.identity_prompt,
            constraints_prompt=req.constraints_prompt,
            allowed_tools=req.allowed_tools,
            description=req.description,
            communication_prompt=req.communication_prompt,
            disable_passivity_correction=req.disable_passivity_correction,
            is_default=req.is_default,
            input_guardrail_prompt=req.input_guardrail_prompt,
            execution_policies=req.execution_policies,
            output_dlp_patterns=req.output_dlp_patterns,
            output_semantic_rules=req.output_semantic_rules,
            approval_mode=req.approval_mode,
            scope_policy=req.scope_policy,
        )
        _invalidate_sessions(app_id=app_id, persona_id=(result or {}).get("persona_id"))
        return result

    def update_app_persona(self, persona_id: int, req: PersonaUpdateRequest) -> Optional[Dict[str, Any]]:
        if not self._persona_repo:
            raise ValueError("PersonaRepository not initialized.")
        update_data = req.model_dump(exclude_none=True)
        result = self._persona_repo.update_persona(persona_id, **update_data)
        _invalidate_sessions(persona_id=persona_id, app_id=(result or {}).get("app_id"))
        return result

    def delete_app_persona(self, persona_id: int) -> bool:
        if not self._persona_repo:
            raise ValueError("PersonaRepository not initialized.")
        existing = self._persona_repo.get_persona(persona_id)
        result = self._persona_repo.delete_persona(persona_id)
        _invalidate_sessions(persona_id=persona_id,
                             app_id=(existing or {}).get("app_id"))
        return result
