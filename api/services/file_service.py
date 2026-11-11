"""File Service — orchestrates the filesystem file store + the canonical
ag_system.files repository, mirroring SMSystems' FileService (file write + DB
row together).

Split of responsibility:
  * core.file_store  → bytes on disk (SMSystems FileHandler/ImageHandler port)
  * FileRepository   → the ag_system.files metadata row (canonical schema)
  * THIS service     → orchestration + base64 hydration for the chat pipeline
                       (Part 1: attachments → model).

Tenant: the canonical files row does NOT store tenant (SMSystems keeps tenant in
the storage PATH); we derive it from the request's tenant context for the path,
and the tenant-scoped DB isolates the rows.
"""
import logging
from typing import Dict, List, Optional, Tuple

from core.file_store import file_store, kind_for_mime, IMG
from core.config import app_config
from core.tenant_context import current_tenant
from api.repositories.file_repo import FileRepository

logger = logging.getLogger(__name__)

# file_type code → the attachment `kind` the agent/LLM layer understands.
_KIND = {"IMG": "image", "DOC": "document", "AUD": "audio", "VID": "video"}

# Images: ONLY the formats every vision model accepts. Excludes bmp/tiff (would
# 400 downstream) and SVG (an XSS vector — never accept it). audio/video are
# prefix-allowed (gated by model capability; providers handle common codecs).
# Documents: PDF only (base64 document blocks are PDF-only across providers).
_ALLOWED_IMAGE = {"image/jpeg", "image/jpg", "image/png", "image/gif", "image/webp"}
_ALLOWED_MIME_PREFIXES = ("audio/", "video/")
_ALLOWED_MIME_EXACT = {"application/pdf"} | _ALLOWED_IMAGE


class FileService:
    def __init__(self, repo: FileRepository, db=None):
        self._repo = repo
        self._db = db

    # ── validation ────────────────────────────────────────────────────────
    @staticmethod
    def _max_bytes() -> int:
        return int(app_config.get("media.max_upload_mb", "20") or 20) * 1024 * 1024

    def validate(self, size: int, mime_type: str) -> Optional[str]:
        if size > self._max_bytes():
            return (f"File is too large (max "
                    f"{app_config.get('media.max_upload_mb', '20')} MB).")
        mt = (mime_type or "").lower()
        if not (mt in _ALLOWED_MIME_EXACT
                or any(mt.startswith(p) for p in _ALLOWED_MIME_PREFIXES)):
            return f"Unsupported file type: {mime_type or 'unknown'}."
        return None

    # ── Part 1: user uploads an attachment ────────────────────────────────
    def save_upload(self, *, data: bytes, filename: str, mime_type: str,
                    user_id: int) -> Dict:
        """Store bytes + create an UNASSIGNED file row (associated_id=0). The
        row is bound to the real message on send (assign_to_message)."""
        file_type = kind_for_mime(mime_type)
        ext = ""
        if filename and "." in filename:
            ext = filename[filename.rfind("."):]
        tenant_id = current_tenant().tenant_id

        written = file_store.write(
            file_type=file_type, extension=ext, data=data,
            associated_to="chat_message", associated_id=0,
            tenant_id=tenant_id, thumbnail=(file_type == IMG))

        row = self._repo.add_file(
            file_type=file_type, associated_to="chat_message", associated_id=0,
            file_path=written["file_path"], file_name=filename, extension=ext,
            mime_type=mime_type, size_bytes=written["size_bytes"],
            created_by=user_id)

        return {
            "fileId": row["file_id"],
            "kind": _KIND.get(file_type, "document"),
            "mediaType": mime_type,
            "fileName": filename,
            "size": written["size_bytes"],
        }

    def assign_to_message(self, file_ids: List[int], message_id: int,
                          user_id: int) -> int:
        return self._repo.assign_files(file_ids, message_id, user_id)

    def bind_generated(self, file_ids: List[int], message_id: int) -> int:
        """Bind model-generated artifacts (Part 2) to the assistant message."""
        return self._repo.bind_generated(file_ids, message_id)

    @staticmethod
    def _meta(r: Dict) -> Dict:
        return {
            "fileId": r["file_id"],
            "kind": _KIND.get(r["file_type"], "document"),
            "mediaType": r.get("mime_type"),
            "fileName": r.get("file_name"),
        }

    def list_for_message(self, message_id: int) -> List[Dict]:
        """Metadata-only (no bytes) attachment list for one message."""
        return [self._meta(r)
                for r in self._repo.get_files_by_assoc("chat_message", message_id)]

    def list_for_messages(self, message_ids: List[int]) -> Dict[int, List[Dict]]:
        """Metadata for many messages in ONE query → {message_id: [meta,...]}.
        Used on conversation load to avoid an N+1."""
        out: Dict[int, List[Dict]] = {}
        for r in self._repo.get_files_for_messages(message_ids):
            out.setdefault(r["associated_id"], []).append(self._meta(r))
        return out

    # ── hydration for the agent (base64) ──────────────────────────────────
    def hydrate_for_message(self, message_id: int) -> List[Dict]:
        """Return [{kind, media_type, data_b64, filename}] for a message's files,
        loaded from disk as base64 (exactly what _convert_history needs)."""
        rows = self._repo.get_files_by_assoc("chat_message", message_id)
        tenant_id = current_tenant().tenant_id
        out: List[Dict] = []
        for r in rows:
            # Images: send the bounded "vision" variant (base64 under provider
            # per-image limits). Docs/others: the original.
            variant = "vision" if r["file_type"] == IMG else None
            b64 = file_store.read_b64(
                file_type=r["file_type"], tenant_id=tenant_id,
                file_path=r["file_path"], variant=variant)
            if b64 is None:
                logger.warning("attachment bytes missing for file_id=%s", r["file_id"])
                continue
            out.append({
                "kind": _KIND.get(r["file_type"], "document"),
                "media_type": r.get("mime_type"),
                "data_b64": b64,
                "filename": r.get("file_name"),
                "file_id": r["file_id"],
            })
        return out

    # ── serving ───────────────────────────────────────────────────────────
    def get_bytes(self, file_id: int, thumbnail: bool = False,
                  user_id: int = None) -> Optional[Tuple[str, bytes]]:
        r = self._repo.get_file(file_id)
        if not r:
            return None
        # Authz: uploader owns it (created_by). Generated 'out' files are owned
        # by the turn's user via created_by too.
        if user_id is not None and r.get("created_by") not in (None, user_id):
            return None
        data = file_store.read(
            file_type=r["file_type"], tenant_id=current_tenant().tenant_id,
            file_path=r["file_path"],
            variant="thumbnail" if thumbnail else None)
        if data is None:
            return None
        return (r.get("mime_type") or "application/octet-stream", data)

    def delete(self, file_id: int, user_id: int) -> bool:
        r = self._repo.get_file(file_id)
        if not r or r.get("created_by") not in (None, user_id):
            return False
        file_store.delete(file_type=r["file_type"],
                          tenant_id=current_tenant().tenant_id,
                          file_path=r["file_path"])
        self._repo.delete_file(file_id)
        return True
