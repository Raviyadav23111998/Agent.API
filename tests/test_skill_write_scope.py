"""A learned skill belongs to the application that learned it.

The reader was never wrong. skill_repo._SCOPE_WHERE matches
scope_type='tenant' unconditionally, which is exactly right — "tenant" means
the whole organisation, across products.

The WRITER was wrong. skill_service.write() resolved _ambient_scope() and then
passed a hardcoded scope_type="tenant" two lines later, so every skill any
agent ever learned became visible to every other application in the tenant.

It leaked both ways, and neither direction was theoretical: one product's exam
questions — answer keys included — ended up in the same index as another
product's ticket-filing procedure, and each was offered to the other as
relevant know-how.
"""

import pytest

from api.services.skill_service import _default_write_scope


# ── the scope a new skill is born with ───────────────────────────────────

def test_an_app_scoped_turn_writes_an_app_scoped_skill():
    assert _default_write_scope(7, 42) == ("app", 7)


def test_the_app_wins_over_the_user():
    # Mirrors the reader's own precedence (skill_repo._SCOPE_RANK: user > app >
    # tenant) from the other side — a skill learned while serving an app is the
    # app's, even though a user was present too.
    scope_type, scope_id = _default_write_scope(3, 99)
    assert scope_type == "app" and scope_id == 3


def test_a_user_turn_with_no_app_writes_a_user_scoped_skill():
    assert _default_write_scope(None, 42) == ("user", 42)


def test_only_a_context_with_neither_falls_back_to_tenant():
    # The local CLI: one operator, nothing to isolate them from. On the server
    # every turn carries an app_id, so nothing lands here by accident.
    assert _default_write_scope(None, None) == ("tenant", None)


def test_tenant_is_never_the_default_when_an_app_is_known():
    # The regression that mattered. If this ever returns "tenant" for a turn
    # that had an app, the leak is back.
    for app_id in (1, 4, 6, 7):
        scope_type, _ = _default_write_scope(app_id, None)
        assert scope_type != "tenant", (
            f"app {app_id} would write a tenant-wide skill again")


def test_string_app_ids_are_coerced():
    # UserContext.app_id is a str ("7"); scope_id is an integer column.
    assert _default_write_scope("7", None) == ("app", 7)


# ── the repository must not have a safe-looking dangerous default ────────

class _FakeDB:
    def __init__(self): self.sql = None
    def execute_returning(self, sql, params=None):
        self.sql = sql
        return {"skill_id": 1, "name": "x", "version": 1}


def _repo():
    from api.repositories.skill_repo import SkillRepository
    return SkillRepository(_FakeDB())


def test_create_refuses_to_guess_a_scope():
    """scope_type used to DEFAULT to 'tenant'.

    That is the widest scope on the platform, and the single caller that could
    have overridden it passed nothing — so every agent-learned skill became
    org-wide. A default that fails OPEN is the bug; the next caller must be
    made to decide rather than arrive here by omission.
    """
    with pytest.raises(ValueError, match="must name its scope"):
        _repo().create("s", "d", "b")


def test_create_refuses_a_scope_id_less_app_scope():
    # scope_type='app' with no scope_id matches no row in _SCOPE_WHERE, so the
    # skill would be written and then be invisible to everyone — the failure
    # that looks like the write silently not happening.
    with pytest.raises(ValueError, match="needs a scope_id"):
        _repo().create("s", "d", "b", scope_type="app")

    with pytest.raises(ValueError, match="needs a scope_id"):
        _repo().create("s", "d", "b", scope_type="user")


def test_create_refuses_an_unknown_scope():
    with pytest.raises(ValueError):
        _repo().create("s", "d", "b", scope_type="global", scope_id=1)


def test_an_explicit_app_scope_is_accepted():
    # Tenant remains possible — deliberately, for an administrator — but has to
    # be spelled out.
    assert _repo().create("s", "d", "b", scope_type="app", scope_id=7)
    assert _repo().create("s", "d", "b", scope_type="tenant")
