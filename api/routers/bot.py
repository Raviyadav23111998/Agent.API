"""
Bot Router — Embeddable Chatbot API Endpoints
══════════════════════════════════════════════════
Auth: X-Bot-Token header (API token, not JWT)

GET  /api/v1/bot/config              → Bot config (name, welcome, theme)
POST /api/v1/bot/chat                → Send message → SSE stream
GET  /api/v1/bot/history/{sessionId} → Conversation history
GET  /bot/widget.js                  → Embeddable JS widget (static)
GET  /bot/demo                       → Demo page

Memory Isolation:
- Anonymous visitors (no userId in request): NO memory capture
- Logged-in users (userId from site's JWT): memory scoped per user per bot

Rate Limiting:
- 30 messages per IP per hour (configurable in BotRateLimiter)
- Returns 429 via SSE error event with retryAfter field
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Request
import fastapi
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Bot"])

BOT_TOKEN_RE = re.compile(r'^ag_bot_[A-Za-z0-9_-]{20,48}$')


class BotChatRequest(BaseModel):
    """Bot chat message request."""
    message: str = Field(..., min_length=1, max_length=8000,
        description="User message")
    session_id: str = Field(..., alias="sessionId",
        description="Browser session ID (from localStorage)")
    page_url: Optional[str] = Field(None, alias="pageUrl",
        description="Current page URL where the bot is embedded")
    user_id: Optional[str] = Field(None, alias="userId",
        description="Logged-in user's unique ID (from site's JWT). "
                    "If provided, enables memory isolation per user. "
                    "If null/absent, bot runs without memory (anonymous).")

    class Config:
        populate_by_name = True


def _get_bot_service(request: Request):
    return request.app.state.bot_service


def _validate_token(x_bot_token: str) -> str:
    """Validate bot token format."""
    if not x_bot_token:
        raise HTTPException(status_code=401, detail="X-Bot-Token header required")
    if not BOT_TOKEN_RE.match(x_bot_token):
        raise HTTPException(status_code=401, detail="Invalid bot token format")
    return x_bot_token


def _validate_domain(request: Request, allowed_domains: list) -> bool:
    """Check if the request origin is in the bot's allowed_domains.
    
    Returns True if allowed, False if blocked.
    Wildcard '*' allows all domains.
    """
    if not allowed_domains or "*" in allowed_domains:
        return True
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    request_domain = urlparse(origin or referer).hostname or ""
    if not request_domain:
        return False
    return any(
        request_domain == d or request_domain.endswith(f".{d}")
        for d in allowed_domains
    )


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, handling proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


@router.get(
    "/v1/bot/config",
    summary="Get bot configuration",
    description="Returns public bot config: name, welcome message, theme color.",
)
async def get_bot_config(
    request: Request,
    response: fastapi.Response,
    x_bot_token: str = Header(..., alias="X-Bot-Token"),
):
    response.headers["Cache-Control"] = "no-cache"
    svc = _get_bot_service(request)
    token = _validate_token(x_bot_token)
    config = svc.get_bot_config(token)
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found or inactive")
    try:
        from core.tenant_context import current_tenant
        router = getattr(request.app.state, "msystem_router", None)
        ctx = current_tenant()
        brand = (router.get_branding(ctx.tenant_id)
                 if router and ctx and getattr(ctx, "tenant_id", None) else {}) or {}
        if brand.get("theme_color") and config.get("theme_color") in (None, "", "#6D28D9"):
            config["theme_color"] = brand["theme_color"]
        from core.tenant_branding import master_logo_url, gateway_base_from_request
        domain = (request.headers.get("x-tenant-domain")
                  or getattr(ctx, "tenant_key", "") or "")
        config["logo_url"] = master_logo_url(
            domain, has_logo=bool(brand.get("logo_url")),
            gateway_base=gateway_base_from_request(request))
        config["org_name"] = brand.get("org_name") or ""
    except Exception:
        pass
    return config


@router.post(
    "/v1/bot/chat",
    summary="Send message — SSE streaming response",
    description="""
    Send a message to the chatbot and receive a streaming response via SSE.
    
    **Required headers:**
    - `X-Bot-Token`: Your bot's API token

    **Optional fields:**
    - `userId`: Logged-in user's unique ID (from site's JWT).
      If provided, the bot remembers user preferences across sessions.
      If omitted, the bot runs in anonymous mode (no memory).

    **Event types:**
    - `message.start` — conversation started
    - `status` — bot state (loading_context, reasoning)
    - `message.delta` — text chunk
    - `tool.start` / `tool.end` — agent tool usage
    - `message.end` — full response
    - `error` — error occurred (check `retryAfter` for rate limits)
    - `ping` — keepalive
    - `[DONE]` — stream complete

    **Rate Limiting:**
    - 30 messages per IP per hour
    - Exceeded: returns SSE error with `retryAfter` field

    **Usage:**
    ```
    curl -N -H "X-Bot-Token: YOUR_TOKEN" \\
         -H "Content-Type: application/json" \\
         -d '{"message": "Hello!", "sessionId": "abc123", "pageUrl": "/pricing", "userId": "user_42"}' \\
         http://localhost:8100/api/v1/bot/chat
    ```
    """,
)
async def bot_chat(
    chat_request: BotChatRequest,
    request: Request,
    x_bot_token: str = Header(..., alias="X-Bot-Token"),
):
    svc = _get_bot_service(request)
    token = _validate_token(x_bot_token)
    client_ip = _get_client_ip(request)
    request_origin = request.headers.get("origin") or request.headers.get("referer", "")

    return StreamingResponse(
        svc.stream_bot_chat(
            api_token=token,
            session_id=chat_request.session_id,
            message=chat_request.message,
            page_url=chat_request.page_url,
            user_id=chat_request.user_id,
            client_ip=client_ip,
            request_origin=request_origin,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


from pydantic import BaseModel


class BotApprovalDecision(BaseModel):
    approved: bool
    reason: Optional[str] = ""


@router.post(
    "/v1/bot/approvals/{approval_id}",
    summary="Approve or deny a pending bot action",
    description="Resolves an `approval.request` SSE event from the widget. "
                "Requires the bot token; the random approval_id is the capability.",
)
async def resolve_bot_approval(
    approval_id: str,
    decision: BotApprovalDecision,
    request: Request,
    x_bot_token: str = Header(..., alias="X-Bot-Token"),
):
    _validate_token(x_bot_token)
    from core.approvals import resolve_approval
    ok = resolve_approval(approval_id, decision.approved, user_id=None,
                          reason=decision.reason or "")
    if not ok:
        raise HTTPException(status_code=404,
                            detail="Approval not found or already resolved")
    return {"approvalId": approval_id, "approved": decision.approved}


@router.get(
    "/v1/bot/history/{session_id}",
    summary="Get conversation history",
    description="Returns the full conversation history for a session.",
)
async def get_bot_history(
    session_id: str,
    request: Request,
    x_bot_token: str = Header(..., alias="X-Bot-Token"),
):
    svc = _get_bot_service(request)
    token = _validate_token(x_bot_token)
    history = svc.get_conversation_history(token, session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Bot or conversation not found")
    return history


@router.get(
    "/bot/widget.js",
    summary="Embeddable chat widget",
    description="Returns the JavaScript file for the embeddable chat widget.",
    include_in_schema=False,
)
async def serve_widget():
    import os
    widget_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "static", "widget.js"
    )
    if not os.path.exists(widget_path):
        raise HTTPException(status_code=404, detail="Widget not found")
    return FileResponse(
        widget_path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get(
    "/bot/demo",
    summary="Demo page",
    description="Demo page showing the chatbot widget in action.",
    include_in_schema=False,
)
async def serve_demo():
    import os
    demo_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "static", "demo.html"
    )
    if not os.path.exists(demo_path):
        raise HTTPException(status_code=404, detail="Demo page not found")
    return FileResponse(demo_path, media_type="text/html")
