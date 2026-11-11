"""
Skill Service — tenant-DB SkillStore implementation + the attach seam.

Implements the engine's SkillStore contract (tools/skills_mcp.py) over
ag_agents.skills (V036). Scope (tenant|app|user) is resolved PER CALL from
the ambient UserContext contextvar — the store object is process-wide (it
hangs off the shared AgentCLI), but every read sees only the calling
session's scope, and TenantDBProxy routes the tenant.

attach_skills(cli, db) is THE way a surface binds procedural memory to a
CLI (twin of llm_scope.attach_scope) — idempotent, never raises, no-op
unless `agent.skill_learning` is enabled for the tenant.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from api.repositories.skill_repo import SkillRepository

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_FILE_KINDS = {"references": "reference", "templates": "template",
               "scripts": "script"}


def _ambient_scope():
    """(app_id, numeric_user_id) from the current turn's UserContext."""
    app_id, uid = None, None
    try:
        from core.user_context import current_user_context
        ctx = current_user_context.get()
        if ctx is not None:
            app_id = getattr(ctx, "app_id", None)
            from api.services.llm_scope import numeric_user_id
            uid = numeric_user_id(getattr(ctx, "user_id", None))
    except Exception:
        pass
    try:
        app_id = int(app_id) if app_id is not None else None
    except (TypeError, ValueError):
        app_id = None
    return app_id, uid


def _default_write_scope(app_id, user_id):
    """Where a newly learned skill belongs, narrowest identity that exists.

    app > user > tenant, mirroring the precedence the reader already applies
    when the same name exists at several scopes (skill_repo._SCOPE_RANK).

    Tenant is the last resort rather than the default, and only survives for
    the case that has no application at all — the local CLI, where there is one
    operator and nothing to isolate them from. On the server every turn carries
    an app_id, so nothing lands here by accident.
    """
    if app_id is not None:
        return "app", int(app_id)
    if user_id is not None:
        return "user", int(user_id)
    return "tenant", None


class TenantSkillStore:
    """SkillStore over the tenant DB. All methods synchronous (called from
    tool threads / to_thread contexts)."""

    def __init__(self, db):
        self._repo = SkillRepository(db)

    # ── Engine contract ──────────────────────────────────────────────────
    def index(self) -> List[Dict]:
        app_id, uid = _ambient_scope()
        return self._repo.index_rows(app_id=app_id, user_id=uid)

    def get(self, name: str) -> Optional[Dict]:
        app_id, uid = _ambient_scope()
        return self._repo.get(name, app_id=app_id, user_id=uid)

    def get_file(self, name: str, path: str) -> Optional[str]:
        app_id, uid = _ambient_scope()
        return self._repo.get_file(name, path, app_id=app_id, user_id=uid)

    def record_use(self, name: str) -> None:
        try:
            app_id, uid = _ambient_scope()
            self._repo.record_use(name, app_id=app_id, user_id=uid)
        except Exception:
            logger.debug("skill use-count failed (ignored)", exc_info=True)

    def write(self, action: str, name: str, *, description: str = None,
              body: str = None, tags=None, file_path: str = None,
              file_content: str = None, edited_by: str = "agent") -> str:
        name = (name or "").strip().lower()
        if not _NAME_RE.match(name or ""):
            return ("Invalid skill name — use lowercase-hyphenated, "
                    "3-64 chars (class-level, not a session artifact).")
        # Attribute the edit to the acting identity so skill_versions.edited_by
        # is a real audit trail ('reviewer'/'curator'/…), not a blanket
        # 'agent'. Explicit callers (admin router: 'user:<id>') are honored.
        if edited_by == "agent":
            edited_by = self._actor()
        # Agent-written content is a prompt surface: block obvious injection
        # at the WRITE, not just at load.
        for text in (body, file_content, description):
            if text and self._looks_injected(text):
                return ("Rejected: content contains instruction-injection "
                        "patterns and was not saved.")

        app_id, uid = _ambient_scope()
        existing = self._repo.get(name, app_id=app_id, user_id=uid)

        if action == "create":
            if existing:
                return (f"Skill '{name}' already exists — use patch/edit, "
                        f"or write_file for supporting detail.")
            if not (description and body):
                return "create needs description and body."

            # A learned skill belongs to the application that learned it.
            #
            # This used to be hardcoded 'tenant' two lines below an
            # _ambient_scope() call that already knew the app — so every skill
            # any agent wrote was visible to every OTHER application in the
            # tenant, because _SCOPE_WHERE matches scope_type='tenant'
            # unconditionally and is right to. The reader was never the
            # problem.
            #
            # It leaked in both directions and neither was theoretical: one
            # product's exam questions, answer keys included, sat in the same
            # index as another product's ticket-filing procedure, and each was
            # offered to the other as relevant know-how.
            #
            # Tenant scope still exists and is still the right answer for a
            # genuine cross-product convention — it is now something an admin
            # states deliberately through the admin router, not somewhere an
            # agent lands by default.
            scope_type, scope_id = _default_write_scope(app_id, uid)

            # An agent may never mint an org-wide skill, whatever the ambient
            # scope resolved to. _default_write_scope only returns 'tenant' when
            # there is neither an app nor a user — the local CLI — and every
            # server entry point sets one. If it somehow does not, a turn that
            # cannot say which application it belongs to must not write
            # something every application can see. That is precisely how
            # create-jira-ticket-scrum ended up in an exam author's prompt.
            if scope_type == "tenant" and app_id is not None:
                return ("Refused: an agent may not create an org-wide skill. "
                        "Tenant scope is an administrator's decision.")

            self._repo.create(name, description[:120], body, tags=tags,
                              scope_type=scope_type, scope_id=scope_id,
                              embedding=self._embed(f"{name}: {description}"))
            self._invalidate()
            return f"Skill '{name}' created."

        if not existing:
            return f"No skill named '{name}'. Use skills_list first."
        if existing.get("origin") == "bundled":
            return f"Skill '{name}' is bundled (read-only)."
        sid = existing["skill_id"]

        if action in ("edit", "patch"):
            if not body:
                return f"{action} needs body."
            self._repo.update_body(
                sid, body, append=(action == "patch"), edited_by=edited_by,
                description=(description[:120] if description else None),
                tags=tags,
                embedding=(self._embed(f"{name}: {description}")
                           if description else None))
            self._invalidate()
            return f"Skill '{name}' {action}ed (v{existing['version'] + 1})."

        if action == "write_file":
            top = (file_path or "").split("/", 1)[0]
            kind = _FILE_KINDS.get(top)
            if not kind or not file_content:
                return ("write_file needs file_content and a file_path under "
                        "references/, templates/ or scripts/.")
            self._repo.write_file(sid, kind, file_path, file_content,
                                  edited_by)
            self._invalidate()
            return f"File '{file_path}' saved under skill '{name}'."

        if action == "remove_file":
            if not file_path:
                return "remove_file needs file_path."
            self._repo.remove_file(sid, file_path, edited_by)
            self._invalidate()
            return f"File '{file_path}' removed from skill '{name}'."

        if action == "archive":
            if self._repo.archive(sid, edited_by):
                self._invalidate()
                return f"Skill '{name}' archived."
            return f"Skill '{name}' is pinned or bundled — not archived."

        return f"Unknown action '{action}'."

    # ── Host-side helpers (learning/curator/admin) ───────────────────────
    def record_correction_after_use(self, names: List[str]) -> None:
        try:
            app_id, uid = _ambient_scope()
            self._repo.record_correction_after_use(names, app_id=app_id,
                                                   user_id=uid)
        except Exception:
            logger.debug("correction-signal write failed", exc_info=True)

    def index_for(self, app_id: Optional[int], user_id: Optional[int]):
        """Explicit-scope index for the SESSION-CREATION prompt snapshot
        (no ambient context on that path)."""
        return self._repo.index_rows(app_id=app_id, user_id=user_id)

    # ── internals ────────────────────────────────────────────────────────
    @staticmethod
    def _actor() -> str:
        """The identity making the edit, for skill_versions.edited_by.
        Spawned agents carry user_id '__agent__<name>__' (create_agent_user)
        → 'reviewer'/'curator'/…; anything else falls back to 'agent'."""
        try:
            from core.user_context import current_user_context
            ctx = current_user_context.get()
            uid = getattr(ctx, "user_id", "") or ""
            if uid.startswith("__agent__") and uid.endswith("__"):
                return uid[len("__agent__"):-2] or "agent"
        except Exception:
            pass
        return "agent"

    @staticmethod
    def _looks_injected(text: str) -> bool:
        try:
            from core.injection_guard import detect_injection
            return bool(detect_injection(text))
        except Exception:
            return False

    @staticmethod
    def _embed(text: str):
        try:
            from core.embeddings import EmbeddingClient
            vec = EmbeddingClient().embed_one(text)
            return vec or None
        except Exception:
            return None  # embedding is an optimization, never a blocker

    @staticmethod
    def _invalidate():
        """Skill edits change the per-session index snapshot — rebuild
        sessions the same way persona/app edits do."""
        try:
            from api.services.chat_service import invalidate_config
            invalidate_config()
        except Exception:
            logger.debug("skills invalidate broadcast failed", exc_info=True)


_store: Optional[TenantSkillStore] = None


def learning_enabled() -> bool:
    try:
        from core.config import app_config
        return app_config.get_bool("agent.skill_learning", False)
    except Exception:
        return False


def get_skill_store(db) -> TenantSkillStore:
    global _store
    if _store is None:
        _store = TenantSkillStore(db)
    return _store


def attach_skills(cli, db=None) -> Optional[TenantSkillStore]:
    """THE seam for binding procedural memory to an AgentCLI (twin of
    attach_scope). No-op (and detaches nothing) when the tenant flag is off;
    idempotent; never raises."""
    try:
        if not learning_enabled():
            return None
        store = get_skill_store(
            db if db is not None else getattr(cli, "tenant_db", None))
        if getattr(cli, "skill_store", None) is None:
            cli.skill_store = store
        return store
    except Exception:
        logger.debug("skills attach failed", exc_info=True)
        return None
