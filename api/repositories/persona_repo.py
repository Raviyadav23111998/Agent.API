"""
Persona Repository — CRUD for ag_system.agent_personas.

Agent Personas define the identity, constraints, communication style,
and deterministic tool whitelist for agents operating under an Application.

Resolution is strict: every bot/agent MUST have a persona linked via
its app_id. There is no fallback to file-based prompts.
"""
import logging
from typing import List, Dict, Any, Optional

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class PersonaRepository:
    """Repository for managing Agent Personas."""

    def __init__(self, db: TenantDB):
        self._db = db

    def get_persona(self, persona_id: int) -> Optional[Dict[str, Any]]:
        """Get a single persona by ID."""
        row = self._db.fetch_one("""
            SELECT * FROM ag_system.agent_personas
            WHERE persona_id = %s AND is_active = TRUE
        """, (persona_id,))
        if row:
            import json
            for field, default in [('allowed_tools', []), ('execution_policies', {}), ('output_dlp_patterns', []), ('scope_policy', {})]:
                if isinstance(row.get(field), str):
                    try:
                        row[field] = json.loads(row[field])
                    except (json.JSONDecodeError, TypeError):
                        row[field] = default
        return row

    def get_persona_for_app(self, app_id: int) -> Optional[Dict[str, Any]]:
        """Get the default persona for an application.

        Strict resolution: returns the default persona for this app_id.
        Returns None if no persona exists — caller must handle this.
        """
        row = self._db.fetch_one("""
            SELECT * FROM ag_system.agent_personas
            WHERE app_id = %s AND is_default = TRUE AND is_active = TRUE
        """, (app_id,))
        if row:
            import json
            for field, default in [('allowed_tools', []), ('execution_policies', {}), ('output_dlp_patterns', []), ('scope_policy', {})]:
                if isinstance(row.get(field), str):
                    try:
                        row[field] = json.loads(row[field])
                    except (json.JSONDecodeError, TypeError):
                        row[field] = default
        return row

    def list_personas(self, app_id: int = None,
                      include_inactive: bool = False) -> List[Dict[str, Any]]:
        """List personas, optionally filtered by app_id."""
        conditions = []
        params = []

        if app_id is not None:
            conditions.append("p.app_id = %s")
            params.append(app_id)
        if not include_inactive:
            conditions.append("p.is_active = TRUE")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self._db.fetch_all(f"""
            SELECT p.*,
                   a.name AS app_name
            FROM ag_system.agent_personas p
            JOIN ag_system.applications a ON a.app_id = p.app_id
            {where}
            ORDER BY p.app_id, p.persona_id
        """, tuple(params) if params else None)
        import json
        for row in rows:
            for field, default in [('allowed_tools', []), ('execution_policies', {}), ('output_dlp_patterns', []), ('scope_policy', {})]:
                if isinstance(row.get(field), str):
                    try:
                        row[field] = json.loads(row[field])
                    except (json.JSONDecodeError, TypeError):
                        row[field] = default
        return rows

    def create_persona(self, app_id: int, name: str,
                       identity_prompt: str,
                       constraints_prompt: str,
                       allowed_tools: list,
                       description: str = "",
                       communication_prompt: str = "Be concise, friendly, and professional. Use markdown formatting.",
                       disable_passivity_correction: bool = True,
                       is_default: bool = False,
                       input_guardrail_prompt: str = None,
                       execution_policies: dict = None,
                       output_dlp_patterns: list = None,
                       output_semantic_rules: str = None,
                       approval_mode: str = None,
                       scope_policy: dict = None) -> Dict[str, Any]:
        """Create a new persona strictly bound to an app_id."""
        import json
        approval_mode = approval_mode or None
        row = self._db.execute_returning("""
            INSERT INTO ag_system.agent_personas
                (app_id, name, description, identity_prompt, constraints_prompt,
                 communication_prompt, allowed_tools, disable_passivity_correction, is_default,
                 input_guardrail_prompt, execution_policies, output_dlp_patterns, output_semantic_rules,
                 approval_mode, scope_policy)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb)
            RETURNING *
        """, (app_id, name, description, identity_prompt, constraints_prompt,
              communication_prompt, json.dumps(allowed_tools),
              disable_passivity_correction, is_default,
              input_guardrail_prompt,
              json.dumps(execution_policies or {}),
              json.dumps(output_dlp_patterns or []),
              output_semantic_rules,
              approval_mode,
              json.dumps(scope_policy or {})))
        if row:
            import json
            for field, default in [('allowed_tools', []), ('execution_policies', {}), ('output_dlp_patterns', []), ('scope_policy', {})]:
                if isinstance(row.get(field), str):
                    try:
                        row[field] = json.loads(row[field])
                    except (json.JSONDecodeError, TypeError):
                        row[field] = default
        logger.info("persona.created: id=%s app=%s name=%s tools=%d",
                    row['persona_id'], app_id, name, len(allowed_tools))
        return row

    def update_persona(self, persona_id: int, **kwargs) -> Optional[Dict[str, Any]]:
        """Update a persona. Only updates fields present in kwargs."""
        import json
        allowed = {'name', 'description', 'identity_prompt', 'constraints_prompt',
                   'communication_prompt', 'allowed_tools',
                   'disable_passivity_correction', 'is_default', 'is_active',
                   'input_guardrail_prompt', 'execution_policies',
                   'output_dlp_patterns', 'output_semantic_rules',
                   'approval_mode', 'scope_policy'}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return self.get_persona(persona_id)

        if updates.get('approval_mode') == '':
            updates['approval_mode'] = None

        if 'allowed_tools' in updates and isinstance(updates['allowed_tools'], list):
            updates['allowed_tools'] = json.dumps(updates['allowed_tools'])
        if 'execution_policies' in updates and isinstance(updates['execution_policies'], dict):
            updates['execution_policies'] = json.dumps(updates['execution_policies'])
        if 'output_dlp_patterns' in updates and isinstance(updates['output_dlp_patterns'], list):
            updates['output_dlp_patterns'] = json.dumps(updates['output_dlp_patterns'])
        if 'scope_policy' in updates and isinstance(updates['scope_policy'], dict):
            updates['scope_policy'] = json.dumps(updates['scope_policy'])

        set_clauses = ", ".join(f"{k} = %s" for k in updates)
        set_clauses += ", updated_at = NOW()"
        params = list(updates.values()) + [persona_id]

        self._db.execute(
            f"UPDATE ag_system.agent_personas SET {set_clauses} WHERE persona_id = %s",
            tuple(params)
        )
        logger.info("persona.updated: id=%s fields=%s", persona_id, list(updates.keys()))
        return self.get_persona(persona_id)

    def delete_persona(self, persona_id: int) -> bool:
        """Soft-delete a persona (set is_active = FALSE)."""
        rows = self._db.execute(
            "UPDATE ag_system.agent_personas SET is_active = FALSE, updated_at = NOW() WHERE persona_id = %s",
            (persona_id,)
        )
        logger.info("persona.deleted: id=%s", persona_id)
        return rows > 0
