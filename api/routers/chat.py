"""
Chat Router — SSE Streaming Endpoints (ChatGPT/Gemini style)
══════════════════════════════════════════════════════════════
POST /api/v1/chat               → Send message, receive SSE stream
GET  /api/v1/chat/conversations → List conversations
GET  /api/v1/chat/conversations/{id}  → Get conversation + messages
DELETE /api/v1/chat/conversations/{id} → Delete conversation
"""

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Query
from fastapi.responses import StreamingResponse

from api.middleware.auth import get_current_user
from api.schemas.chat import (
    ChatRequest, ConversationDTO,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/chat", tags=["Chat"])


class _ChatRateLimiter:
    """M4 — per-user sliding-window cap on the authenticated chat endpoint.

    The engine already bounds cost per turn (concurrency semaphore + the
    conversation token budget); this stops a script from firing a burst of
    expensive turns. Generous by design — it never blocks a human's normal
    pace, only runaway automation. In-process (best-effort per worker); the
    per-turn engine budgets remain the hard cost guard.
    """

    def __init__(self, max_requests: int = 40, window_s: int = 60):
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


_chat_rate_limiter = _ChatRateLimiter()


def _get_chat_service(request: Request):
    return request.app.state.chat_service


from pydantic import BaseModel


class ApprovalDecision(BaseModel):
    approved: bool
    reason: Optional[str] = ""


@router.post(
    "/approvals/{approval_id}",
    summary="Approve or deny a pending irreversible action",
    description="Resolves an `approval.request` SSE event. Only the user who "
                "owns the conversation can resolve their approvals.",
)
async def resolve_approval_endpoint(
    approval_id: str,
    decision: ApprovalDecision,
    current_user: Dict = Depends(get_current_user),
):
    from core.approvals import resolve_approval
    user_id = int(current_user.get("user_ID", 0))
    ok = resolve_approval(
        approval_id, decision.approved,
        user_id=user_id, reason=decision.reason or "",
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Approval not found, already resolved, or not yours",
        )
    return {"approvalId": approval_id, "approved": decision.approved}


@router.post(
    "",
    summary="Send message — SSE streaming response",
    description="""
    Send a message and receive a streaming response via Server-Sent Events (SSE).
    
    **Event types:**
    - `message.start` — conversation created/resumed
    - `status` — agent state (loading_context, reasoning)
    - `message.delta` — text chunk (streamed token)
    - `tool.start` / `tool.end` — tool execution events
    - `message.end` — final message with full content
    - `error` — error occurred
    - `[DONE]` — stream complete
    
    **Usage with curl:**
    ```
    curl -N -H "Authorization: Bearer TOKEN" \\
         -H "Content-Type: application/json" \\
         -d '{"message": "Hello!"}' \\
         http://localhost:8100/api/v1/chat
    ```
    """,
)
async def chat(
    chat_request: ChatRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user),
    x_ag_source: str = Header('web', alias='X-AG-Source'),
):
    svc = _get_chat_service(request)
    user_id = int(current_user.get("user_ID", 0))
    source = x_ag_source or 'web'

    # M4 — per-user request-rate cap (runaway-automation guard).
    if not _chat_rate_limiter.check(user_id):
        raise HTTPException(
            status_code=429,
            detail="You're sending messages too quickly. Please slow down and try again shortly.")

    try:
        conv = svc.get_or_create_conversation(
            conversation_id=chat_request.conversation_id,
            user_id=user_id,
            agent_id=chat_request.agent_id,
            model=chat_request.model or '',
            source=source,
        )

        conversation_id = conv["conversation_id"]
        app_id = current_user.get("app_id")

        if chat_request.stream:
            return StreamingResponse(
                svc.stream_chat(
                    conversation_id=conversation_id,
                    user_message=chat_request.message,
                    user_id=user_id,
                    model=chat_request.model,
                    app_id=int(app_id) if app_id is not None else None,
                    user_role=current_user.get("role", ""),
                    attachment_ids=chat_request.attachment_ids,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            result = await svc.chat_sync(
                conversation_id=conversation_id,
                user_message=chat_request.message,
                user_id=user_id,
                model=chat_request.model,
                user_role=current_user.get("role", ""),
            )
            return result

    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/conversations",
    response_model=List[ConversationDTO],
    summary="List conversations",
)
async def list_conversations(
    request: Request,
    limit: int = Query(50, le=100),
    current_user: Dict = Depends(get_current_user),
    x_ag_source: str = Header('web', alias='X-AG-Source'),
):
    svc = _get_chat_service(request)
    user_id = int(current_user.get("user_ID", 0))
    source = x_ag_source or 'web'
    return svc.list_conversations(user_id, source=source)


@router.get(
    "/conversations/{conversation_id}",
    summary="Get conversation with messages",
)
async def get_conversation(
    conversation_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_chat_service(request)
    user_id = int(current_user.get("user_ID", 0))
    detail = svc.get_conversation_detail(conversation_id, user_id=user_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.delete(
    "/conversations/{conversation_id}",
    summary="Delete conversation",
)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_chat_service(request)
    user_id = int(current_user.get("user_ID", 0))
    svc.delete_conversation(conversation_id, user_id=user_id)
    return {"message": "Conversation deleted"}
