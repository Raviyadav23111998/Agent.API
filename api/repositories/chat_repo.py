"""
Chat Repository — Conversation + Message persistence.
═══════════════════════════════════════════════════════
Tables: ag_system.conversations, ag_system.messages
"""
import json
import logging
from typing import Optional, List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)

# The marker that separates a key-owned conversation from a person's.
#
# A service conversation stores user_id = the key's service_user_id, which is a
# REAL user row (V040 does that on purpose so llm_scope budgets, the token
# ledger and the dashboards keep working with no notion of "service"). The cost
# is that every human read scoped by user_id alone — the sidebar, "open this
# thread", "delete this thread" — would otherwise hand the admin who minted the
# key every one of the caller's end-user threads. So the human paths below
# exclude this source explicitly.
#
# Why `source` and not `service_key_id IS NULL`, which reads better: source is
# NOT NULL with a default and has existed since the bootstrap schema, whereas
# service_key_id arrives only with V040. These are the hot paths on every tenant
# database, including ones that will never have V040 applied — predicating them
# on a column that may not exist would turn a privacy fix into an outage on
# exactly the databases that have no service keys to protect against. On those,
# this predicate is simply always true.
SERVICE_SOURCE = 'service'


class ChatRepository:
    """Data access for conversations and messages."""

    def __init__(self, db: TenantDB):
        self._db = db


    def create_conversation(self, conversation_id: str, user_id: int,
                            title: str = '', agent_id: int = None,
                            model: str = '', source: str = 'web') -> Dict:
        return self._db.execute_returning("""
            INSERT INTO ag_system.conversations
                (conversation_id, user_id, title, agent_id, model, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING conversation_id, user_id, title, agent_id, model,
                      message_count, is_archived, source, created_at, updated_at
        """, (conversation_id, user_id, title, agent_id, model, source))

    # ══════════════════ conversations owned by a service key ═════════════
    # A service conversation belongs to a KEY acting for one of the caller's
    # end users, not to a person who can sign in here. Ownership is therefore
    # (service_key_id, end_user_ref) and every read below filters on BOTH —
    # matching on the conversation id alone would let one backend's learner
    # fetch another's thread by guessing a uuid. See V040.

    def create_service_conversation(self, conversation_id: str, *,
                                    service_key_id: int, end_user_ref: str,
                                    user_id: int, title: str = '',
                                    model: str = '') -> Dict:
        """Open a thread owned by a key on behalf of one of its end users.

        `source` is NOT a parameter. It is the marker the human-facing reads
        exclude on (see SERVICE_SOURCE), so letting a caller choose it would
        let a service conversation be minted that looks like a person's and
        surfaces in that person's sidebar. Fixed by construction instead.
        """
        return self._db.execute_returning("""
            INSERT INTO ag_system.conversations
                (conversation_id, user_id, title, model, source,
                 service_key_id, end_user_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING conversation_id, user_id, title, agent_id, model,
                      message_count, is_archived, source, service_key_id,
                      end_user_ref, created_at, updated_at
        """, (conversation_id, user_id, title, model, SERVICE_SOURCE,
              service_key_id, end_user_ref))

    def get_service_conversation(self, conversation_id: str, *,
                                 service_key_id: int,
                                 end_user_ref: str) -> Optional[Dict]:
        return self._db.fetch_one("""
            SELECT conversation_id, user_id, title, agent_id, model,
                   message_count, is_archived, source, service_key_id,
                   end_user_ref, created_at, updated_at
            FROM ag_system.conversations
            WHERE conversation_id = %s
              AND service_key_id = %s
              AND end_user_ref = %s
        """, (conversation_id, service_key_id, end_user_ref))

    def list_service_conversations(self, *, service_key_id: int,
                                   end_user_ref: str,
                                   limit: int = 50) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT conversation_id, user_id, title, agent_id, model,
                   message_count, is_archived, source, service_key_id,
                   end_user_ref, created_at, updated_at
            FROM ag_system.conversations
            WHERE service_key_id = %s AND end_user_ref = %s
              AND is_archived = FALSE
            ORDER BY updated_at DESC LIMIT %s
        """, (service_key_id, end_user_ref, limit))

    def delete_service_conversation(self, conversation_id: str, *,
                                    service_key_id: int,
                                    end_user_ref: str) -> int:
        return self._db.execute("""
            DELETE FROM ag_system.conversations
            WHERE conversation_id = %s
              AND service_key_id = %s
              AND end_user_ref = %s
        """, (conversation_id, service_key_id, end_user_ref))

    def get_conversation(self, conversation_id: str, user_id: int = None) -> Optional[Dict]:
        """Get conversation — optionally filtered by user_id for ownership check.

        The user_id branch is a HUMAN ownership check, so it also excludes
        service-owned threads: they carry the key's service_user_id, and
        without this the admin who minted a key could open any of the calling
        backend's end-user conversations. Service reads have their own scoped
        accessor — get_service_conversation.
        """
        if user_id is not None:
            return self._db.fetch_one("""
                SELECT conversation_id, user_id, title, agent_id, model,
                       message_count, is_archived, source, created_at, updated_at
                FROM ag_system.conversations
                WHERE conversation_id = %s AND user_id = %s
                  AND source <> %s
            """, (conversation_id, user_id, SERVICE_SOURCE))
        return self._db.fetch_one("""
            SELECT conversation_id, user_id, title, agent_id, model,
                   message_count, is_archived, source, created_at, updated_at
            FROM ag_system.conversations
            WHERE conversation_id = %s
        """, (conversation_id,))

    def list_conversations(self, user_id: int, limit: int = 50,
                           source: str = None) -> List[Dict]:
        """A person's own threads.

        Service-owned threads are excluded from BOTH branches — including when
        source='service' is asked for explicitly, which would otherwise make
        this a way to read a backend's end-user transcripts through the
        signed-in chat API.
        """
        if source:
            return self._db.fetch_all("""
                SELECT conversation_id, user_id, title, agent_id, model,
                       message_count, is_archived, source, created_at, updated_at
                FROM ag_system.conversations
                WHERE user_id = %s AND is_archived = FALSE AND source = %s
                  AND source <> %s
                ORDER BY updated_at DESC LIMIT %s
            """, (user_id, source, SERVICE_SOURCE, limit))
        return self._db.fetch_all("""
            SELECT conversation_id, user_id, title, agent_id, model,
                   message_count, is_archived, source, created_at, updated_at
            FROM ag_system.conversations
            WHERE user_id = %s AND is_archived = FALSE
              AND source <> %s
            ORDER BY updated_at DESC LIMIT %s
        """, (user_id, SERVICE_SOURCE, limit))

    def try_claim_conversation(self, conversation_id: str,
                               claim_seconds: int = 900) -> bool:
        """Atomically claim a conversation for processing (multi-worker safety).

        Two workers processing the same conversation concurrently would
        interleave history writes. The UPDATE … WHERE free is atomic in PG,
        so exactly one worker wins. Stale claims (crashed worker) expire via
        the timestamp — no cleanup job needed. (Requires migration V012;
        degrades to claim-always-succeeds on older databases.)
        """
        try:
            count = self._db.execute("""
                UPDATE ag_system.conversations
                SET processing_until = NOW() + (%s || ' seconds')::interval
                WHERE conversation_id = %s
                  AND (processing_until IS NULL OR processing_until < NOW())
            """, (str(claim_seconds), conversation_id))
            return count > 0
        except Exception:
            return True

    def release_conversation_claim(self, conversation_id: str):
        """Release the processing claim (call when processing finishes)."""
        try:
            self._db.execute("""
                UPDATE ag_system.conversations
                SET processing_until = NULL
                WHERE conversation_id = %s
            """, (conversation_id,))
        except Exception:
            pass

    def update_conversation_title(self, conversation_id: str, title: str):
        self._db.execute("""
            UPDATE ag_system.conversations SET title = %s WHERE conversation_id = %s
        """, (title, conversation_id))

    def increment_message_count(self, conversation_id: str, count: int = 1):
        self._db.execute("""
            UPDATE ag_system.conversations
            SET message_count = message_count + %s
            WHERE conversation_id = %s
        """, (count, conversation_id))

    def write_action_audit(self, user_id, conversation_id, tool_name,
                           side_effect, args_summary, approved, status):
        """Append a side-effecting action to the audit trail (best-effort)."""
        try:
            self._db.execute("""
                INSERT INTO ag_system.action_audit
                    (user_id, conversation_id, tool_name, side_effect,
                     args_summary, approved, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, conversation_id, tool_name, side_effect,
                  args_summary, approved, status))
        except Exception:
            pass

    def archive_conversation(self, conversation_id: str):
        self._db.execute("""
            UPDATE ag_system.conversations SET is_archived = TRUE
            WHERE conversation_id = %s
        """, (conversation_id,))

    def delete_conversation(self, conversation_id: str, user_id: int = None):
        """Delete conversation — scoped to user_id for ownership safety.

        Same exclusion as the read path: a person deleting "their" threads must
        not be able to destroy a calling backend's end-user transcripts that
        happen to spend against their user row.
        """
        if user_id is not None:
            self._db.execute("""
                DELETE FROM ag_system.conversations
                WHERE conversation_id = %s AND user_id = %s
                  AND source <> %s
            """, (conversation_id, user_id, SERVICE_SOURCE))
        else:
            self._db.execute("""
                DELETE FROM ag_system.conversations WHERE conversation_id = %s
            """, (conversation_id,))


    def add_message(self, conversation_id: str, role: str, content: str = '',
                    tool_calls: list = None, tool_call_id: str = None,
                    token_count: int = 0, metadata: dict = None) -> Dict:
        tc_json = json.dumps(tool_calls) if tool_calls else '[]'
        meta_json = json.dumps(metadata) if metadata else '{}'
        return self._db.execute_returning("""
            INSERT INTO ag_system.messages
                (conversation_id, role, content, tool_calls, tool_call_id,
                 token_count, metadata_json)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
            RETURNING message_id, conversation_id, role, content,
                      tool_calls, created_at
        """, (conversation_id, role, content, tc_json, tool_call_id,
              token_count, meta_json))

    def get_messages(self, conversation_id: str, limit: int = 100) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT message_id, conversation_id, role, content,
                   tool_calls, tool_call_id, token_count, created_at
            FROM ag_system.messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC LIMIT %s
        """, (conversation_id, limit))

    def get_recent_messages(self, conversation_id: str, limit: int = 20) -> List[Dict]:
        """Get most recent messages (for context loading)."""
        rows = self._db.fetch_all("""
            SELECT message_id, role, content, tool_calls, tool_call_id
            FROM ag_system.messages
            WHERE conversation_id = %s
            ORDER BY created_at DESC LIMIT %s
        """, (conversation_id, limit))
        return list(reversed(rows))
