"""
Agent Router — REST endpoints for agent management.
════════════════════════════════════════════════════
"""
import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import get_current_user, is_admin
from api.schemas.agent import AgentCreateRequest, AgentDTO, AgentRunDTO, AgentRunRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/agents", tags=["Agents"])


def _get_agent_service(request: Request):
    return request.app.state.agent_service


@router.get("", response_model=List[AgentDTO], summary="List agents")
async def list_agents(request: Request, current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    if is_admin(current_user):
        return await svc.list_agents(user_id=None)
    uid = int(current_user.get("user_ID", 0))
    return await svc.list_agents(user_id=uid)


@router.get("/{agent_id}", response_model=AgentDTO, summary="Get agent")
async def get_agent(agent_id: int, request: Request,
                    current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    uid = None if is_admin(current_user) else int(current_user.get("user_ID", 0))
    agent = await svc.get_agent(agent_id, user_id=uid)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("", summary="Create agent")
async def create_agent(req: AgentCreateRequest, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    uid = int(current_user.get("user_ID", 0))
    result = await svc.create_agent(req, created_by=uid)
    return result


@router.put("/{agent_id}", summary="Update agent")
async def update_agent(agent_id: int, req: AgentCreateRequest, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    uid = int(current_user.get("user_ID", 0))
    return await svc.update_agent(agent_id, req, user_id=uid)


@router.delete("/{agent_id}", summary="Delete agent")
async def delete_agent(agent_id: int, request: Request,
                       current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    uid = int(current_user.get("user_ID", 0))
    await svc.delete_agent(agent_id, user_id=uid)
    return {"message": "Agent deleted"}


@router.post("/{agent_id}/run", response_model=AgentRunDTO, summary="Run agent")
async def run_agent(agent_id: int, req: AgentRunRequest, request: Request,
                    current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    uid = int(current_user.get("user_ID", 0))
    try:
        return await svc.run_agent(agent_id, req.prompt, triggered_by=uid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}/runs", response_model=List[AgentRunDTO], summary="Run history")
async def list_runs(agent_id: int, request: Request,
                    current_user: Dict = Depends(get_current_user)):
    svc = _get_agent_service(request)
    return await svc.list_runs(agent_id)
