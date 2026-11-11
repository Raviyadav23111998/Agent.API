"""
Service key primitives — long-lived server-to-server credentials.
═══════════════════════════════════════════════════════════════════════════
  ag_sk_live_<43 url-safe chars>
  └────┬────┘└──────┬──────┘
       │            └── secrets.token_urlsafe(32); never stored, only hashed
       └── environment marker, so a test key pasted into a prod config is
           visible at a glance rather than after a confusing 401

Sibling to security/embed_keys.py, and deliberately NOT the same thing:

  ag_pk_ / ag_sk_  (embed)    a BROWSER key. Public half in a <script>, origin
                              allowlist, exchanged for a 15-minute session JWT.
  ag_sk_live_      (service)  a BACKEND key. No origin, no handshake, no
                              expiry by default — presented on every request.

Storage rule, same as embed: the raw key is returned to the admin exactly once
at mint and never again. What we keep is sha256(key) plus a clear-text prefix
for lookup and display. A database dump therefore contains no usable key.

See V040_service_api_keys.sql.
"""
import hashlib
import hmac
import re
import secrets

PREFIX = "ag_sk_live_"

# 43 chars is what token_urlsafe(32) produces; accept a little slack so a
# future widening of the entropy does not invalidate the format check.
KEY_RE = re.compile(r"^ag_sk_live_[A-Za-z0-9_-]{32,}$")

# What goes in the key_prefix column: the marker plus enough of the body to
# tell two keys apart in a list, and far too little to brute-force from.
PREFIX_DISPLAY_CHARS = 6


def mint() -> str:
    """A fresh key. The only place the raw value ever exists in full."""
    return PREFIX + secrets.token_urlsafe(32)


def is_well_formed(key: str) -> bool:
    """Cheap shape check, run before touching the database.

    An auth path that queries on every malformed string is a free way to make
    us do work on someone else's behalf.
    """
    return bool(key and KEY_RE.match(key))


def prefix_of(key: str) -> str:
    """The clear-text lookup handle, e.g. 'ag_sk_live_7Kq2xF'."""
    return key[: len(PREFIX) + PREFIX_DISPLAY_CHARS]


def hash_key(key: str) -> str:
    """sha256 hex of the full key — what the database stores.

    Deliberately a plain hash and not bcrypt/argon2: this runs on every single
    request, and the input is 256 bits of CSPRNG output rather than a human
    password. There is no dictionary to slow an attacker down against, so the
    stretching would only slow US down.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify(key: str, stored_hash: str) -> bool:
    """Constant-time compare of a presented key against a stored hash."""
    if not key or not stored_hash:
        return False
    return hmac.compare_digest(hash_key(key), stored_hash)


def mask(key_prefix: str) -> str:
    """How a key is shown after mint — never the key, only its handle."""
    return f"{key_prefix}…"
