"""File Repository — ag_system.files (the canonical bootstrap table, shared with
SMSystems' file model).

Canonical columns (ag_system.files, from bootstrap):
    file_id, file_type, associated_to, associated_id, file_path, file_name,
    extension, size_bytes, mime_type, created_by, created_at

Polymorphic association: a chat attachment is associated_to='chat_message',
associated_id=<message_id>. Bytes live on the filesystem (core.file_store);
this row holds metadata + the RELATIVE file_path. Freshly-uploaded files carry
associated_id=0 (unassigned) until bound to a message on send.
"""
import logging
from typing import Optional, List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)

_COLS = ("file_id, file_type, associated_to, associated_id, file_path, "
         "file_name, extension, size_bytes, mime_type, created_by, created_at")


class FileRepository:
    def __init__(self, db: TenantDB):
        self._db = db

    def add_file(self, *, file_type: str, associated_to: str,
                 associated_id: int, file_path: str, file_name: str = None,
                 extension: str = None, mime_type: str = None,
                 size_bytes: int = 0, created_by: int = None) -> Dict:
        return self._db.execute_returning(f"""
            INSERT INTO ag_system.files
                (file_type, associated_to, associated_id, file_path,
                 file_name, extension, mime_type, size_bytes, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING {_COLS}
        """, (file_type, associated_to, associated_id, file_path,
              file_name, extension, mime_type, size_bytes, created_by))

    def get_file(self, file_id: int) -> Optional[Dict]:
        return self._db.fetch_one(
            f"SELECT {_COLS} FROM ag_system.files WHERE file_id = %s", (file_id,))

    def get_files_by_assoc(self, associated_to: str,
                           associated_id: int) -> List[Dict]:
        return self._db.fetch_all(f"""
            SELECT {_COLS} FROM ag_system.files
            WHERE associated_to = %s AND associated_id = %s
            ORDER BY file_id
        """, (associated_to, associated_id))

    def get_files_for_messages(self, message_ids: List[int]) -> List[Dict]:
        """All files for many messages in ONE query (avoids N+1 on conversation
        load). Uses the (associated_to, associated_id) index."""
        if not message_ids:
            return []
        return self._db.fetch_all(f"""
            SELECT {_COLS} FROM ag_system.files
            WHERE associated_to = 'chat_message' AND associated_id = ANY(%s)
            ORDER BY associated_id, file_id
        """, (list(message_ids),))

    def assign_files(self, file_ids: List[int], associated_id: int,
                     user_id: int) -> int:
        """Bind freshly-uploaded (unassigned, associated_id=0) files owned by
        this user to a real message_id. Returns rows updated — the caller uses
        this to reject cross-user / already-bound file ids.

        execute_returning_all, NOT fetch_all. fetch_all opens its cursor with
        commit=False because it is a READ helper, so this UPDATE was rolled back
        on every call — silently, with RETURNING still handing back the rows it
        was about to discard. Every attachment therefore stayed at
        associated_id=0, hydrate_for_message found nothing to send, and the model
        answered about pictures it never received. Nothing failed; the feature
        just did not work.
        """
        if not file_ids:
            return 0
        rows = self._db.execute_returning_all("""
            UPDATE ag_system.files
               SET associated_id = %s
             WHERE file_id = ANY(%s) AND created_by = %s
               AND associated_to = 'chat_message' AND associated_id = 0
            RETURNING file_id
        """, (associated_id, list(file_ids), user_id))
        return len(rows or [])

    def bind_generated(self, file_ids: List[int], associated_id: int) -> int:
        """Bind model-GENERATED (Part 2) files to a message. No owner filter —
        these ids are server-originated (emitted by the agent's own tool this
        turn), not client-supplied.

        execute_returning_all for the same reason as assign_files: fetch_all does
        not commit, so a generated artefact was never bound to the message that
        produced it.
        """
        if not file_ids:
            return 0
        rows = self._db.execute_returning_all("""
            UPDATE ag_system.files
               SET associated_id = %s
             WHERE file_id = ANY(%s)
               AND associated_to = 'chat_message' AND associated_id = 0
            RETURNING file_id
        """, (associated_id, list(file_ids)))
        return len(rows or [])

    def delete_file(self, file_id: int) -> None:
        self._db.execute("DELETE FROM ag_system.files WHERE file_id = %s",
                         (file_id,))
