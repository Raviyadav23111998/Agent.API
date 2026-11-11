"""Files & capabilities router — mirrors the SMSystems FileController surface.

  POST   /v1/files                     upload an attachment (multipart)
  GET    /v1/files/{file_id}           metadata + base64 (SMSystems GET /File/{id})
  GET    /v1/media/{file_id}           raw bytes (for <img src> / <video>)
  DELETE /v1/files/{file_id}           delete
  GET    /v1/capabilities              multimodal matrix for the SELECTED model
                                       (drives the composer's warning)
"""
import base64
import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import APIRouter, Depends, Request, HTTPException, UploadFile, File, Query
from fastapi.responses import Response

from api.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["Files"])


class _UploadRateLimiter:
    """Per-user sliding-window cap on uploads — a runaway-automation / disk-fill
    guard (in-process, best-effort per worker)."""

    def __init__(self, max_requests: int = 60, window_s: int = 60):
        self.max_requests = max_requests
        self.window_s = window_s
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = {}

    def check(self, user_id: int) -> bool:
        key = str(user_id)
        now = time.time()
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            cutoff = now - self.window_s
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_requests:
                return False
            dq.append(now)
            return True


_upload_rate_limiter = _UploadRateLimiter()


def _svc(request: Request):
    return request.app.state.file_service


@router.post("/files", summary="Upload an attachment")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: Dict = Depends(get_current_user),
):
    svc = _svc(request)
    user_id = int(current_user.get("user_ID", 0))

    if not _upload_rate_limiter.check(user_id):
        raise HTTPException(status_code=429,
                            detail="Too many uploads — slow down and retry shortly.")

    data = await file.read()
    media_type = file.content_type or "application/octet-stream"

    err = svc.validate(len(data), media_type)
    if err:
        raise HTTPException(status_code=400, detail=err)

    try:
        return svc.save_upload(data=data, filename=file.filename,
                               mime_type=media_type, user_id=user_id)
    except Exception:
        logger.exception("attachment upload failed for user %s", user_id)
        raise HTTPException(status_code=500,
                            detail="Could not store the file. Please try again.")


@router.get("/files/{file_id}", summary="Get file metadata + base64")
async def get_file(
    file_id: int,
    request: Request,
    thumbnail: bool = Query(False),
    current_user: Dict = Depends(get_current_user),
):
    svc = _svc(request)
    user_id = int(current_user.get("user_ID", 0))
    got = svc.get_bytes(file_id, thumbnail=thumbnail, user_id=user_id)
    if not got:
        raise HTTPException(status_code=404, detail="File not found")
    media_type, data = got
    return {"fileId": file_id, "mediaType": media_type,
            "data": base64.b64encode(data).decode("ascii")}


@router.get("/media/{file_id}", summary="Serve raw file bytes")
async def get_media(
    file_id: int,
    request: Request,
    thumbnail: bool = Query(False),
    current_user: Dict = Depends(get_current_user),
):
    svc = _svc(request)
    user_id = int(current_user.get("user_ID", 0))
    got = svc.get_bytes(file_id, thumbnail=thumbnail, user_id=user_id)
    if not got:
        raise HTTPException(status_code=404, detail="File not found")
    media_type, data = got
    return Response(content=data, media_type=media_type,
                    headers={"Cache-Control": "private, max-age=86400"})


@router.delete("/files/{file_id}", summary="Delete a file")
async def delete_file(
    file_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _svc(request)
    user_id = int(current_user.get("user_ID", 0))
    if not svc.delete(file_id, user_id):
        raise HTTPException(status_code=404, detail="File not found")
    return {"deleted": file_id}


@router.get("/capabilities", summary="Multimodal capabilities of the selected model")
async def capabilities(
    request: Request,
    model: Optional[str] = Query(None, description="Selected model id; omit for the effective default"),
    current_user: Dict = Depends(get_current_user),
):
    """Returns the input/output × image/audio/video matrix for the EFFECTIVE model
    (resolved agent-def > request > user > app profile, same as a real turn) so the
    composer can WARN (not silently drop) when the user attaches — or asks the model
    to generate — a type the model can't handle."""
    chat_service = request.app.state.chat_service
    user_id = int(current_user.get("user_ID", 0))
    app_id = current_user.get("app_id")
    return chat_service.resolve_capabilities(
        user_id=user_id,
        app_id=int(app_id) if app_id is not None else None,
        requested_model=model)
