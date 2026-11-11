"""
Agent Repository — Data access for ag_agents.definitions + ag_agents.runs.
══════════════════════════════════════════════════════════════════════════
"""
import json
import logging
from typing import Optional, List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class AgentRepository:
    def __init__(self, db: TenantDB):
        self._db = db


    def list_agents(self, user_id: int = None, enabled_only: bool = False) -> List[Dict]:
        """List agents visible to user: global visibility OR created_by this user."""
        filters = []
        params = []
        if enabled_only:
            filters.append("enabled = TRUE")
        if user_id is not None:
            filters.append("(visibility = 'global' OR created_by = %s)")
            params.append(user_id)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        sql = f"""
            SELECT agent_id, name, description, model, schedule, enabled,
                   deliver, visibility, run_count, last_run_at, last_status,
                   created_by, created_at, updated_at
            FROM ag_agents.definitions {where}
            ORDER BY agent_id DESC
        """
        return self._db.fetch_all(sql, tuple(params) if params else None)

    def get_agent(self, agent_id: int, user_id: int = None) -> Optional[Dict]:
        """Get agent — scoped by visibility: global or owned by user."""
        if user_id:
            return self._db.fetch_one("""
                SELECT agent_id, name, description, system_prompt, tools, model,
                       schedule, enabled, workspace_path, deliver, visibility,
                       metadata_json, run_count, last_run_at, last_status, last_error,
                       created_by, created_at, updated_at
                FROM ag_agents.definitions
                WHERE agent_id = %s AND (visibility = 'global' OR created_by = %s)
            """, (agent_id, user_id))
        return self._db.fetch_one("""
            SELECT agent_id, name, description, system_prompt, tools, model,
                   schedule, enabled, workspace_path, deliver, visibility,
                   metadata_json, run_count, last_run_at, last_status, last_error,
                   created_by, created_at, updated_at
            FROM ag_agents.definitions WHERE agent_id = %s
        """, (agent_id,))

    def create_agent(self, name: str, description: str = None,
                     system_prompt: str = '', tools: list = None,
                     model: str = '', schedule: str = '',
                     enabled: bool = True, workspace_path: str = '',
                     deliver: str = 'local', visibility: str = 'global',
                     metadata: dict = None, created_by: int = None) -> Dict:
        tools_json = json.dumps(tools or [])
        meta_json = json.dumps(metadata or {})
        return self._db.execute_returning("""
            INSERT INTO ag_agents.definitions
                (name, description, system_prompt, tools, model, schedule,
                 enabled, workspace_path, deliver, visibility, metadata_json,
                 created_by)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING agent_id, name, description, enabled, created_at
        """, (name, description, system_prompt, tools_json, model, schedule,
              enabled, workspace_path, deliver, visibility, meta_json, created_by))

    def update_agent(self, agent_id: int, user_id: int = None, name: str = None,
                     description: str = None, system_prompt: str = None,
                     tools: list = None, model: str = None,
                     schedule: str = None, enabled: bool = None,
                     deliver: str = None, visibility: str = None,
                     metadata: dict = None):
        sets, params = [], []
        if name is not None: sets.append("name = %s"); params.append(name)
        if description is not None: sets.append("description = %s"); params.append(description)
        if system_prompt is not None: sets.append("system_prompt = %s"); params.append(system_prompt)
        if tools is not None: sets.append("tools = %s::jsonb"); params.append(json.dumps(tools))
        if model is not None: sets.append("model = %s"); params.append(model)
        if schedule is not None: sets.append("schedule = %s"); params.append(schedule)
        if enabled is not None: sets.append("enabled = %s"); params.append(enabled)
        if deliver is not None: sets.append("deliver = %s"); params.append(deliver)
        if visibility is not None: sets.append("visibility = %s"); params.append(visibility)
        if metadata is not None: sets.append("metadata_json = %s::jsonb"); params.append(json.dumps(metadata))
        if not sets:
            return
        ownership = "AND created_by = %s" if user_id is not None else ""
        params.append(agent_id)
        if user_id is not None:
            params.append(user_id)
        self._db.execute(f"""
            UPDATE ag_agents.definitions SET {', '.join(sets)}
            WHERE agent_id = %s {ownership}
        """, tuple(params))

    def delete_agent(self, agent_id: int, user_id: int = None):
        """Delete agent — scoped by user_id for ownership."""
        if user_id is not None:
            self._db.execute("""
                DELETE FROM ag_agents.definitions
                WHERE agent_id = %s AND created_by = %s
            """, (agent_id, user_id))
        else:
            self._db.execute("DELETE FROM ag_agents.definitions WHERE agent_id = %s", (agent_id,))


    def create_run(self, agent_id: int, input_prompt: str = None,
                   triggered_by: int = None) -> Dict:
        return self._db.execute_returning("""
            INSERT INTO ag_agents.runs (agent_id, status, input_prompt, triggered_by)
            VALUES (%s, 'running', %s, %s)
            RETURNING run_id, agent_id, status, started_at
        """, (agent_id, input_prompt, triggered_by))

    def complete_run(self, run_id: int, output_text: str,
                     status: str = 'ok', error_message: str = None,
                     duration_ms: int = None, token_count: int = None):
        self._db.execute("""
            UPDATE ag_agents.runs SET
                status = %s, output_text = %s, error_message = %s,
                completed_at = ag_common.utc_now(),
                duration_ms = %s, token_count = %s
            WHERE run_id = %s
        """, (status, output_text, error_message, duration_ms, token_count, run_id))

    def list_runs(self, agent_id: int, limit: int = 20) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT run_id, agent_id, status, input_prompt, output_text,
                   error_message, started_at, completed_at, duration_ms, token_count
            FROM ag_agents.runs
            WHERE agent_id = %s ORDER BY started_at DESC LIMIT %s
        """, (agent_id, limit))

    def update_agent_last_run(self, agent_id: int, status: str, error: str = None):
        self._db.execute("""
            UPDATE ag_agents.definitions SET
                last_run_at = ag_common.utc_now(), last_status = %s,
                last_error = %s, run_count = run_count + 1
            WHERE agent_id = %s
        """, (status, error or '', agent_id))
