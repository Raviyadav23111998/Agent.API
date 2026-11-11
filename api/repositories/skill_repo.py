"""
Skill Repository — ag_agents.skills / skill_files / skill_versions (V036).

Tenant-DB procedural memory behind the engine's SkillStore contract
(tools/skills_mcp.py). Scope model mirrors llm_profiles: a session sees
tenant-wide skills + its app's + its user's; user > app > tenant on name
collision. Columns are qualified in every JOIN (V035 lesson).
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SKILL_COLS = ("s.skill_id, s.name, s.description, s.tags, s.body, "
              "s.scope_type, s.scope_id, s.origin, s.pinned, s.is_active, "
              "s.version, s.use_count, s.correction_after_use, "
              "s.created_at, s.updated_at")

_SCOPE_WHERE = ("s.is_active AND (s.scope_type = 'tenant' "
                "OR (s.scope_type = 'app'  AND s.scope_id = %s) "
                "OR (s.scope_type = 'user' AND s.scope_id = %s))")


class SkillRepository:

    def __init__(self, db):
        self._db = db

    # ── Reads ────────────────────────────────────────────────────────────
    def index_rows(self, app_id: Optional[int] = None,
                   user_id: Optional[int] = None) -> List[Dict]:
        """Lightweight index for the prompt snapshot + skills_list.
        user > app > tenant wins on duplicate names."""
        rows = self._db.fetch_all(
            f"SELECT s.name, s.description, s.tags, s.pinned, s.origin, "
            f"s.scope_type FROM ag_agents.skills s WHERE {_SCOPE_WHERE} "
            f"ORDER BY s.name", (app_id, user_id)) or []
        rank = {"user": 2, "app": 1, "tenant": 0}
        best: Dict[str, Dict] = {}
        for r in rows:
            cur = best.get(r["name"])
            if cur is None or rank[r["scope_type"]] > rank[cur["scope_type"]]:
                best[r["name"]] = r
        return sorted(best.values(), key=lambda r: r["name"])

    def get(self, name: str, app_id: Optional[int] = None,
            user_id: Optional[int] = None) -> Optional[Dict]:
        row = self._db.fetch_one(
            f"SELECT {SKILL_COLS} FROM ag_agents.skills s "
            f"WHERE s.name = %s AND {_SCOPE_WHERE} "
            f"ORDER BY CASE s.scope_type WHEN 'user' THEN 2 "
            f"WHEN 'app' THEN 1 ELSE 0 END DESC LIMIT 1",
            (name, app_id, user_id))
        if not row:
            return None
        files = self._db.fetch_all(
            "SELECT kind, path FROM ag_agents.skill_files "
            "WHERE skill_id = %s ORDER BY path", (row["skill_id"],)) or []
        row["files"] = files
        return row

    def get_file(self, name: str, path: str, app_id=None,
                 user_id=None) -> Optional[str]:
        skill = self.get(name, app_id, user_id)
        if not skill:
            return None
        row = self._db.fetch_one(
            "SELECT content FROM ag_agents.skill_files "
            "WHERE skill_id = %s AND path = %s", (skill["skill_id"], path))
        return row["content"] if row else None

    def list_all(self, include_inactive=True) -> List[Dict]:
        where = "" if include_inactive else "WHERE s.is_active"
        return self._db.fetch_all(
            f"SELECT {SKILL_COLS} FROM ag_agents.skills s {where} "
            f"ORDER BY s.is_active DESC, s.name") or []

    # ── Writes (all snapshot into skill_versions) ────────────────────────
    def _snapshot(self, skill_id: int, edited_by: str):
        row = self._db.fetch_one(
            "SELECT version, body FROM ag_agents.skills s WHERE s.skill_id = %s",
            (skill_id,))
        if not row:
            return
        files = self._db.fetch_all(
            "SELECT path, content FROM ag_agents.skill_files WHERE skill_id = %s",
            (skill_id,)) or []
        self._db.execute(
            "INSERT INTO ag_agents.skill_versions "
            "(skill_id, version, body, files, edited_by) VALUES (%s,%s,%s,%s,%s)",
            (skill_id, row["version"], row["body"],
             json.dumps({f["path"]: f["content"] for f in files}), edited_by))

    def create(self, name: str, description: str, body: str, tags=None,
               scope_type=None, scope_id=None, origin="agent",
               created_by=None, embedding=None) -> Dict:
        """Insert a skill. scope_type is REQUIRED — there is no safe default.

        It used to default to 'tenant', and every agent-learned skill on the
        platform took it, because the one caller that could have overridden it
        passed nothing. 'tenant' means org-wide and _SCOPE_WHERE matches it
        unconditionally, so a skill one product learned was advertised to every
        other product — including apps holding none of the tools it depends on.

        A default that is the widest possible scope is a default that fails
        open. Making it required means the next caller has to decide, and
        cannot arrive here by omission.
        """
        if scope_type not in ("app", "user", "tenant"):
            raise ValueError(
                f"scope_type must be 'app', 'user' or 'tenant' — got {scope_type!r}. "
                "A skill must name its scope; 'tenant' is org-wide and has to be "
                "chosen deliberately, never fallen into.")

        if scope_type in ("app", "user") and scope_id is None:
            raise ValueError(
                f"scope_type={scope_type!r} needs a scope_id, or the row matches "
                "nothing and the skill is invisible to everyone.")

        # embedding column exists only where pgvector does — name it only
        # when we actually have a vector to store.
        cols = "name, description, tags, body, scope_type, scope_id, origin, created_by"
        vals = [name, description, list(tags or []), body, scope_type,
                scope_id, origin, created_by]
        ph = "%s,%s,%s,%s,%s,%s,%s,%s"
        if embedding is not None:
            cols += ", embedding"
            vals.append(embedding)
            ph += ",%s"
        return self._db.execute_returning(
            f"INSERT INTO ag_agents.skills ({cols}) VALUES ({ph}) "
            f"RETURNING skill_id, name, version", tuple(vals))

    def update_body(self, skill_id: int, body: str, *, append: bool,
                    edited_by: str, description=None, tags=None,
                    embedding=None) -> None:
        self._snapshot(skill_id, edited_by)
        sets, vals = [], []
        if append:
            sets.append("body = body || %s")
            vals.append("\n\n" + body)
        else:
            sets.append("body = %s")
            vals.append(body)
        if description:
            sets.append("description = %s")
            vals.append(description)
        if tags is not None:
            sets.append("tags = %s")
            vals.append(list(tags))
        if embedding is not None:
            sets.append("embedding = %s")
            vals.append(embedding)
        vals.append(skill_id)
        self._db.execute(
            f"UPDATE ag_agents.skills SET {', '.join(sets)}, "
            f"version = version + 1, updated_at = now() WHERE skill_id = %s",
            tuple(vals))

    def update_meta(self, skill_id: int, *, edited_by: str, description=None,
                    tags=None, embedding=None) -> None:
        """Update description/tags (never the body). Admin edits that touch
        only metadata must not clobber the SKILL.md body."""
        sets, vals = [], []
        if description is not None:
            sets.append("description = %s")
            vals.append(description[:120])
        if tags is not None:
            sets.append("tags = %s")
            vals.append(list(tags))
        if embedding is not None:
            sets.append("embedding = %s")
            vals.append(embedding)
        if not sets:
            return
        self._snapshot(skill_id, edited_by)
        vals.append(skill_id)
        self._db.execute(
            f"UPDATE ag_agents.skills SET {', '.join(sets)}, "
            f"version = version + 1, updated_at = now() WHERE skill_id = %s",
            tuple(vals))

    def write_file(self, skill_id: int, kind: str, path: str, content: str,
                   edited_by: str) -> None:
        self._snapshot(skill_id, edited_by)
        self._db.execute(
            "INSERT INTO ag_agents.skill_files (skill_id, kind, path, content) "
            "VALUES (%s,%s,%s,%s) ON CONFLICT (skill_id, path) DO UPDATE SET "
            "content = EXCLUDED.content, updated_at = now()",
            (skill_id, kind, path, content))
        self._db.execute(
            "UPDATE ag_agents.skills SET version = version + 1, "
            "updated_at = now() WHERE skill_id = %s", (skill_id,))

    def remove_file(self, skill_id: int, path: str, edited_by: str) -> None:
        self._snapshot(skill_id, edited_by)
        self._db.execute(
            "DELETE FROM ag_agents.skill_files WHERE skill_id = %s AND path = %s",
            (skill_id, path))

    def archive(self, skill_id: int, edited_by: str) -> bool:
        """Soft-archive. Pinned and bundled skills are store-protected."""
        self._snapshot(skill_id, edited_by)
        row = self._db.execute_returning(
            "UPDATE ag_agents.skills SET is_active = FALSE, updated_at = now() "
            "WHERE skill_id = %s AND NOT pinned AND origin <> 'bundled' "
            "RETURNING skill_id", (skill_id,))
        return bool(row)

    def set_pinned(self, skill_id: int, pinned: bool) -> None:
        self._db.execute(
            "UPDATE ag_agents.skills SET pinned = %s, updated_at = now() "
            "WHERE skill_id = %s", (pinned, skill_id))

    def restore_version(self, skill_id: int, version: int,
                        edited_by: str) -> bool:
        old = self._db.fetch_one(
            "SELECT body FROM ag_agents.skill_versions "
            "WHERE skill_id = %s AND version = %s "
            "ORDER BY version_id DESC LIMIT 1", (skill_id, version))
        if not old:
            return False
        self.update_body(skill_id, old["body"], append=False,
                         edited_by=edited_by)
        return True

    def versions(self, skill_id: int) -> List[Dict]:
        return self._db.fetch_all(
            "SELECT version_id, version, edited_by, created_at "
            "FROM ag_agents.skill_versions WHERE skill_id = %s "
            "ORDER BY version_id DESC LIMIT 50", (skill_id,)) or []

    # ── Effectiveness signals ────────────────────────────────────────────
    # Both bump the SAME row get() would resolve for this scope (user > app >
    # tenant) — never every row that happens to share the name, which would
    # corrupt the very signal the curator ranks on.
    _SCOPE_RANK = ("CASE scope_type WHEN 'user' THEN 2 "
                   "WHEN 'app' THEN 1 ELSE 0 END DESC")

    def record_use(self, name: str, app_id: Optional[int] = None,
                   user_id: Optional[int] = None) -> None:
        self._db.execute(
            "UPDATE ag_agents.skills SET use_count = use_count + 1, "
            "last_used_at = now() WHERE skill_id = ("
            f"SELECT s.skill_id FROM ag_agents.skills s WHERE s.name = %s "
            f"AND {_SCOPE_WHERE} ORDER BY {self._SCOPE_RANK} LIMIT 1)",
            (name, app_id, user_id))

    def record_correction_after_use(self, names: List[str],
                                    app_id: Optional[int] = None,
                                    user_id: Optional[int] = None) -> None:
        if not names:
            return
        self._db.execute(
            "UPDATE ag_agents.skills SET correction_after_use = "
            "correction_after_use + 1 WHERE skill_id IN ("
            "SELECT DISTINCT ON (s.name) s.skill_id FROM ag_agents.skills s "
            f"WHERE s.name = ANY(%s) AND {_SCOPE_WHERE} "
            f"ORDER BY s.name, {self._SCOPE_RANK})",
            (names, app_id, user_id))
