"""
Agent Service — Business logic for agent management + execution.
═══════════════════════════════════════════════════════════════
"""
import time
import logging
from typing import List, Dict, Optional

from api.repositories.agent_repo import AgentRepository
from api.schemas.agent import AgentCreateRequest, AgentDTO, AgentRunDTO

logger = logging.getLogger(__name__)


class AgentService:
    def __init__(self, repo: AgentRepository):
        self._repo = repo

    async def list_agents(self, user_id: int = None, enabled_only: bool = False) -> List[AgentDTO]:
        rows = self._repo.list_agents(user_id=user_id, enabled_only=enabled_only)
        return [AgentDTO(**r) for r in rows]

    async def get_agent(self, agent_id: int, user_id: int = None) -> Optional[AgentDTO]:
        row = self._repo.get_agent(agent_id, user_id=user_id)
        if not row:
            return None
        return AgentDTO(**row)

    async def create_agent(self, req: AgentCreateRequest,
                           created_by: int = None) -> Dict:
        return self._repo.create_agent(
            name=req.name, description=req.description,
            system_prompt=req.system_prompt or '',
            tools=req.tools, model=req.model or '',
            schedule=req.schedule or '', enabled=req.enabled,
            workspace_path=req.workspace_path or '',
            deliver=req.deliver, visibility=req.visibility,
            metadata=req.metadata, created_by=created_by,
        )

    async def update_agent(self, agent_id: int, req: AgentCreateRequest,
                           user_id: int = None):
        self._repo.update_agent(
            agent_id=agent_id, user_id=user_id, name=req.name,
            description=req.description,
            system_prompt=req.system_prompt,
            tools=req.tools, model=req.model,
            schedule=req.schedule, enabled=req.enabled,
            deliver=req.deliver, visibility=req.visibility,
            metadata=req.metadata,
        )
        return {"agentId": agent_id, "message": "Agent updated"}

    async def delete_agent(self, agent_id: int, user_id: int = None):
        self._repo.delete_agent(agent_id, user_id=user_id)

    async def run_agent(self, agent_id: int, prompt: str = None,
                        triggered_by: int = None) -> AgentRunDTO:
        """Execute an agent run — routes through full AgentLoop (50 tools)."""
        agent = self._repo.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        run = self._repo.create_run(agent_id, prompt, triggered_by)
        run_id = run["run_id"]
        start = time.time()

        try:
            from api.services.chat_service import _session_pool
            import asyncio

            session = await _session_pool.get_session(
                conversation_id=f"agent-run-{run_id}",
                user_id=triggered_by or 0,
                user_name=f"agent_run_{agent_id}",
                approval_mode="off",
            )
            agent_loop = session.agent

            if agent.get("system_prompt"):
                agent_loop.prompt_builder._custom_system_prompt = agent["system_prompt"]

            response_queue = asyncio.Queue()

            async def _capture(payload):
                await response_queue.put(payload)

            agent_loop.event_bus.subscribe('agent_response', _capture)
            try:
                user_msg = prompt or "Execute your task."
                task = asyncio.create_task(
                    agent_loop._process_input({"user_input": user_msg})
                )

                result = await asyncio.wait_for(response_queue.get(), timeout=120.0)
                output = result.get("message", "")
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            finally:
                agent_loop.event_bus.unsubscribe('agent_response', _capture)
                if hasattr(agent_loop.prompt_builder, '_custom_system_prompt'):
                    agent_loop.prompt_builder._custom_system_prompt = None
                _session_pool.invalidate(f"agent-run-{run_id}")

            tokens = len(output.split()) if output else 0
            duration_ms = int((time.time() - start) * 1000)
            self._repo.complete_run(run_id, output, "ok", duration_ms=duration_ms, token_count=tokens)
            self._repo.update_agent_last_run(agent_id, "ok")

            return AgentRunDTO(
                run_id=run_id, agent_id=agent_id, status="ok",
                input_prompt=prompt, output_text=output,
                started_at=run["started_at"],
                duration_ms=duration_ms, token_count=tokens,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._repo.complete_run(run_id, "", "error", str(e), duration_ms)
            self._repo.update_agent_last_run(agent_id, "error", str(e))
            raise

    async def list_runs(self, agent_id: int) -> List[AgentRunDTO]:
        rows = self._repo.list_runs(agent_id)
        return [AgentRunDTO(**r) for r in rows]
