"""A service key may bring its own provider credential — and only that.

Two deployments of one product (PrepCrest production and PrepCrest UAT) call
the same applications, so their spend landed on one OpenRouter key: one
monthly limit for both, and no way to cap UAT without capping production.

The existing lever — a profile bound to the key's service user — is the wrong
shape: it wins over the application's profile and replaces the MODEL too, and
the evaluators and the authors deliberately run different models.

So V058 adds a credential to the key, not a profile. These tests pin the two
pure pieces: how the row resolves to a key, and how the key is laid over a
resolved profile without touching anything else.
"""

import pytest

from api.repositories.service_key_repo import resolve_llm_credential
from api.services.llm_scope import credential_ref, with_credential


# ── resolving the row ────────────────────────────────────────────────────

def test_a_key_without_an_override_resolves_to_none():
    assert resolve_llm_credential({"key_id": 1, "llm_api_key": None}) is None
    assert resolve_llm_credential({"key_id": 1, "llm_api_key": ""}) is None


def test_a_raw_key_is_taken_as_written():
    row = {"key_id": 1, "llm_api_key": "  sk-or-v1-abc  "}
    assert resolve_llm_credential(row) == "sk-or-v1-abc"


def test_a_sentinel_resolves_to_the_joined_config_value():
    row = {"key_id": 1, "llm_api_key": "__config:llm.api_key.prepcrest_prod__",
           "llm_api_key_config": "sk-or-v1-prod"}
    assert resolve_llm_credential(row) == "sk-or-v1-prod"


def test_a_sentinel_whose_config_is_missing_falls_back_rather_than_sending_nothing(caplog):
    # The lesser failure: the key spends on the profile's credential and says
    # so in the log. An empty bearer would fail every turn instead.
    row = {"key_id": 7, "llm_api_key": "__config:llm.api_key.typo__",
           "llm_api_key_config": None}
    with caplog.at_level("WARNING"):
        assert resolve_llm_credential(row) is None
    assert "llm.api_key.typo" in caplog.text and "key 7" in caplog.text


# ── laying the credential over the profile ───────────────────────────────

PROFILE = {"profile_id": 7, "name": "prepcrest-authoring", "provider": "openrouter",
           "model": "deepseek/deepseek-v4-flash", "base_url": "https://openrouter.ai/api/v1",
           "api_key": "sk-or-v1-shared", "temperature": None, "updated_at": "2026-09-01"}


def test_no_override_returns_the_very_same_profile_object():
    # Identity, not equality: the plain profile's cached client must be reused.
    assert with_credential(PROFILE, None) is PROFILE
    assert with_credential(PROFILE, "") is PROFILE


def test_an_override_equal_to_the_profiles_own_key_is_also_a_no_op():
    assert with_credential(PROFILE, "sk-or-v1-shared") is PROFILE


def test_an_override_replaces_the_key_and_nothing_else():
    out = with_credential(PROFILE, "sk-or-v1-prod")
    assert out is not PROFILE
    assert out["api_key"] == "sk-or-v1-prod"
    assert out["credential_ref"] == credential_ref("sk-or-v1-prod")
    for k in ("profile_id", "name", "provider", "model", "base_url", "temperature", "updated_at"):
        assert out[k] == PROFILE[k], k
    # …and the original was not mutated.
    assert PROFILE["api_key"] == "sk-or-v1-shared" and "credential_ref" not in PROFILE


def test_two_credentials_on_one_profile_have_distinct_refs():
    # get_profile_client folds credential_ref into its cache key, so this is
    # what keeps a production key and a UAT key from evicting each other.
    a = with_credential(PROFILE, "sk-or-v1-prod")
    b = with_credential(PROFILE, "sk-or-v1-uat")
    assert a["credential_ref"] != b["credential_ref"]
    assert len(a["credential_ref"]) == 12 and "sk-or" not in a["credential_ref"]


def test_a_tenant_without_profiles_still_gets_the_override():
    out = with_credential(None, "sk-or-v1-prod")
    assert out == {"api_key": "sk-or-v1-prod", "credential_ref": credential_ref("sk-or-v1-prod")}
    assert with_credential(None, None) is None
