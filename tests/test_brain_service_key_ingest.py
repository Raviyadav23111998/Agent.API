"""A backend may write to the knowledge base, but not because it may chat.

Before this, the only credential these endpoints accepted was a JWT — a human
with a login, a session and a refresh cycle. A product keeping the knowledge
base in step with its own content has none of those, so its only route in was
to write to ag_brain.documents DIRECTLY: around the API, past the owner, app and
scope rules this router exists to enforce, and past any chance of the platform
ever changing how a document is stored.

Accepting a service key removes the reason to do that. What it must not do is
let an existing key inherit the new power. PrepCrest's key is minted to ANSWER
learners' questions and lives on a server handling every learner request; if
`chat` also meant "may rewrite what the answers are drawn from", one leaked key
would turn a study assistant into a publishing channel.

Hence a distinct scope, and hence these tests: the interesting cases are all
about what a caller is REFUSED.
"""

import pytest
from fastapi import HTTPException

from api.middleware.api_key_auth import is_service, require_scope
from api.routers.brain import _is_admin, _require, _resolve_app_id


def service(**over):
    """A service principal, as require_service_key builds one."""
    p = {"scope": "service", "key_id": 9, "app_id": 15, "user_ID": 42,
         "role": "service", "scopes": ["chat"]}
    p.update(over)
    return p


def human(**over):
    p = {"user_ID": 7, "app_id": 15, "role": "user"}
    p.update(over)
    return p


# ── chat is not a licence to write ───────────────────────────────────────

def test_a_chat_key_may_not_ingest():
    # The whole point. This is the key PrepCrest already holds.
    with pytest.raises(HTTPException) as e:
        _require(service(scopes=["chat"]), "brain:write")
    assert e.value.status_code == 403


def test_a_chat_key_may_not_search_either():
    with pytest.raises(HTTPException) as e:
        _require(service(scopes=["chat"]), "brain:read")
    assert e.value.status_code == 403


def test_a_key_granted_the_scope_may_ingest():
    _require(service(scopes=["chat", "brain:write"]), "brain:write")


def test_read_and_write_are_separable():
    # A key that syncs content need not be able to query it back, and a key that
    # only reads must never be able to write.
    _require(service(scopes=["brain:read"]), "brain:read")
    with pytest.raises(HTTPException):
        _require(service(scopes=["brain:read"]), "brain:write")


# ── humans are unaffected ────────────────────────────────────────────────

def test_a_signed_in_human_is_not_asked_for_scopes():
    # Scopes are a property of a KEY. Asking a JWT for one would refuse every
    # existing user of these endpoints — the regression this guards.
    _require(human(), "brain:write")
    _require(human(), "brain:read")


def test_is_service_tells_the_two_apart():
    assert is_service(service())
    assert not is_service(human())


# ── an app-scoped credential stays app-scoped ────────────────────────────

def test_a_service_key_is_never_admin():
    # role="service" must not appear in the admin list, or a key could ask for
    # appId=0 and reach every application in the tenant.
    assert not _is_admin(service())
    assert not _is_admin(service(role="service"))


def test_a_service_key_cannot_widen_its_app():
    # It asks for app 1 and for "all apps"; it gets its own app both times.
    assert _resolve_app_id(service(app_id=15), 1) == 15
    assert _resolve_app_id(service(app_id=15), 0) == 15


def test_an_admin_still_can():
    admin = human(role="admin")
    assert _resolve_app_id(admin, 0) is None
    assert _resolve_app_id(admin, 3) == 3


def test_a_regular_human_cannot_widen_either():
    assert _resolve_app_id(human(app_id=15), 0) == 15


def test_an_unbound_key_is_refused_in_its_own_words():
    # Fail closed either way, but a backend has no login, so "please re-login"
    # would send whoever is holding the failure nowhere useful.
    with pytest.raises(HTTPException) as e:
        _resolve_app_id(service(app_id=None))
    assert e.value.status_code == 403
    assert "re-login" not in e.value.detail.lower()


def test_an_unbound_human_is_still_told_to_re_login():
    with pytest.raises(HTTPException) as e:
        _resolve_app_id(human(app_id=None))
    assert "re-login" in e.value.detail.lower()


# ── deletion is scoped to the app, which it was not ──────────────────────

class _RecordingDb:
    def __init__(self):
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self.params = params or ()


def _repo():
    from api.repositories.brain_repo import BrainRepository

    db = _RecordingDb()
    repo = BrainRepository(db)
    return repo, db


def test_a_delete_is_confined_to_one_app():
    # The gap: ingestion writes owner_id='__tenant__' by design, so filtering on
    # owner alone made every ingested document deletable by any signed-in user
    # of any OTHER application in the tenant.
    repo, db = _repo()
    repo.delete_document(5, owner_id="7", app_id=15)

    assert "app_id = %s" in db.sql
    assert 15 in db.params


def test_an_admin_delete_is_still_unscoped():
    # The regression this guards is in the FIX, not the bug. Scoping admins to
    # their own app_id would close the hole by breaking the console that manages
    # other applications' documents — reads already let an admin cross apps, and
    # deletion is reached from the same screen. Only regular users narrow.
    repo, db = _repo()
    repo.delete_document(5, owner_id="7", app_id=None)

    assert "app_id" not in db.sql
    assert db.params == (5, "7")


def test_the_router_leaves_an_admin_unscoped_and_narrows_everyone_else():
    from api.routers.brain import _is_admin, _resolve_app_id

    def effective(principal):
        return None if _is_admin(principal) else _resolve_app_id(principal)

    assert effective(human(role="admin", app_id=1)) is None
    assert effective(human(role="user", app_id=1)) == 1


def test_app_zero_is_a_real_app_and_not_a_missing_one():
    # `if app_id:` would drop a filter for app 0. `is not None` is load-bearing.
    repo, db = _repo()
    repo.delete_document(5, owner_id="7", app_id=0)

    assert "app_id = %s" in db.sql
