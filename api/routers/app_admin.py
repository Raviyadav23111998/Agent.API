"""
Application Admin Router — CRUD endpoints for managing applications.
═════════════════════════════════════════════════════════════════════
"""
import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import require_admin
from api.schemas.app_admin import (
    ApplicationDTO, ApplicationCreateRequest, ApplicationUpdateRequest
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/apps", tags=["Application Admin"])


def _get_app_service(request: Request):
    return request.app.state.app_service


@router.get("", response_model=List[ApplicationDTO], response_model_by_alias=True,
            summary="List all applications")
async def list_apps(request: Request, current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    return await svc.list_apps()


@router.post("", response_model=ApplicationDTO, response_model_by_alias=True,
             summary="Create an application")
async def create_app(req: ApplicationCreateRequest, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    uid = int(current_user.get("user_ID", 0))
    try:
        return await svc.create_app(req, user_id=uid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tools", summary="Get all available agent tools")
async def get_available_tools(request: Request, current_user: Dict = Depends(require_admin)):
    tools = [
        "view_file","write_to_file","list_dir","grep_search","replace_file_content","multi_replace_file_content","run_command",
        "schedule","manage_task","cron_list","cron_remove","add_memory","get_memories","search_web","ask_question",
        "query_neo4j","search_elasticsearch","fetch_recent_emails","search_emails","brain_ingest_file","brain_ingest_directory",
        "brain_ingest_text","brain_ingest_current_chat","brain_ask","brain_search","brain_stats","brain_sync","brain_sync_status",
        "brain_fetch","memory_recall","memory_store","memory_stats","memory_forget","memory_user_context","memory_entity_link",
        "memory_company_store","mark_email_processed","agent_create","agent_list","agent_run","agent_delete","agent_logs",
        "outlook_reply","outlook_send","outlook_forward","teams_send_message","teams_notify_me","teams_post_channel","teams_list_channels",
        "send_email_smtp","fetch_emails_imap","jira_create_ticket","jira_update_ticket","jira_transition_ticket","jira_add_comment",
        "jira_add_worklog","jira_list_tickets","git_branch",
        "git_commit","git_status","git_diff",
        "page_observe","page_act","page_navigate","page_read","page_wait",
        "skills_list","skill_view","skill_manage",
    ]
    return tools


@router.get("/{app_id}", response_model=ApplicationDTO, response_model_by_alias=True,
            summary="Get application details")
async def get_app(app_id: int, request: Request,
                  current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    app = await svc.get_app(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.put("/{app_id}", response_model=ApplicationDTO, response_model_by_alias=True,
            summary="Update an application")
async def update_app(app_id: int, req: ApplicationUpdateRequest, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    try:
        app = await svc.update_app(app_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return app


@router.delete("/{app_id}", summary="Delete an application (soft)")
async def delete_app(app_id: int, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    try:
        await svc.delete_app(app_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Application deleted"}


from api.schemas.app_admin import PersonaDTO, PersonaCreateRequest, PersonaUpdateRequest

@router.get("/{app_id}/personas", response_model=List[PersonaDTO], response_model_by_alias=True,
            summary="List all personas for an application")
async def list_personas(app_id: int, request: Request, current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    try:
        personas = svc.list_app_personas(app_id)
        import logging
        logger = logging.getLogger(__name__)
        for p in personas:
            try:
                PersonaDTO(**p)
            except Exception as e:
                logger.error(f"Pydantic Validation failed for persona: {p}", exc_info=True)
        return personas
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Failed to list personas", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/personas", response_model=PersonaDTO, response_model_by_alias=True,
             summary="Create a new persona for an application")
async def create_persona(app_id: int, req: PersonaCreateRequest, request: Request,
                         current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    try:
        return svc.create_app_persona(app_id, req)
    except Exception as e:
        logger.error(f"Failed to create persona: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/personas/{persona_id}", response_model=PersonaDTO, response_model_by_alias=True,
            summary="Update an application persona")
async def update_persona(persona_id: int, req: PersonaUpdateRequest, request: Request,
                         current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    try:
        persona = svc.update_app_persona(persona_id, req)
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        return persona
    except Exception as e:
        logger.error(f"Failed to update persona: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/personas/{persona_id}", summary="Delete an application persona")
async def delete_persona(persona_id: int, request: Request,
                         current_user: Dict = Depends(require_admin)):
    svc = _get_app_service(request)
    try:
        success = svc.delete_app_persona(persona_id)
        if not success:
            raise HTTPException(status_code=404, detail="Persona not found")
        return {"message": "Persona deleted"}
    except Exception as e:
        logger.error(f"Failed to delete persona: {e}")
        raise HTTPException(status_code=400, detail=str(e))
