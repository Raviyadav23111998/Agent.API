"""
WebSocket Router — Bidirectional tool execution for VS Code "Local Server" mode.
════════════════════════════════════════════════════════════════════════════════

Architecture:
    VS Code Extension ←→ WebSocket ←→ This endpoint ←→ Agent Loop ←→ LLM

Protocol (Client → Server):
    {"type": "auth", "token": "Bearer eyJ..."}
    {"type": "chat", "message": "...", "conversationId": "...", "context": {...}}
    {"type": "tool_result", "requestId": "...", "result": "..."}
    {"type": "tool_error", "requestId": "...", "error": "..."}
    {"type": "stop"}

Protocol (Server → Client):
    {"type": "event", "event": "message.start|status|message.delta|tool.start|tool.end|message.end|done", ...}
    {"type": "tool_request", "requestId": "...", "toolName": "...", "toolArgs": {...}}
    {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = logging.getLogger("agent.ws")

router = APIRouter(tags=["WebSocket"])


@router.get("/v1/ws", include_in_schema=False)
async def websocket_probe():
    """Diagnostic shim. A WebSocket route only matches a real Upgrade handshake;
    a plain HTTP GET to the same path would otherwise 404 — indistinguishable from
    the route not being deployed. This returns 426 so ops can tell the difference:
    426 here = the build IS deployed and the problem is the proxy/client not
    upgrading; 404 = the build predates this route. The WS upgrade still hits the
    websocket handler below, not this."""
    return JSONResponse(
        status_code=426,
        content={
            "detail": "Upgrade Required",
            "hint": "This endpoint is WebSocket-only. Connect with a WS client "
                    "(wss://…/api/agent/v1/ws). If you see this over plain HTTP, the "
                    "route is deployed — ensure the reverse proxy forwards the "
                    "Connection/Upgrade headers and Cloudflare WebSockets are enabled.",
        },
        headers={"Upgrade": "websocket", "Connection": "Upgrade"},
    )


_active_executors: Dict[int, "RemoteToolExecutor"] = {}


@router.websocket("/v1/ws")
async def websocket_chat(websocket: WebSocket):
    """Bidirectional WebSocket endpoint for VS Code 'Local Server' mode.
    
    Flow:
    1. Client connects and sends {"type": "auth", "token": "Bearer ..."}
    2. Server validates JWT, replies {"type": "auth_ok"}
    3. Client sends {"type": "chat", ...}
    4. Server runs agent loop as a background task, sends events
    5. Meanwhile, main loop keeps receiving tool_result/stop messages
    6. Chat completes, sends message.end + done
    
    CRITICAL: The message receive loop and chat processing run CONCURRENTLY.
    This prevents deadlock when RemoteToolExecutor sends tool_request
    and waits for tool_result from the same WebSocket connection.
    """
    await websocket.accept()
    logger.info("WebSocket: New connection from %s", websocket.client)

    user_data: Optional[Dict] = None
    chat_task: Optional[asyncio.Task] = None

    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        
        if auth_msg.get("type") != "auth":
            await websocket.send_json({
                "type": "error", 
                "message": "First message must be auth"
            })
            await websocket.close(code=4001, reason="Auth required")
            return

        token = auth_msg.get("token", "")
        if token.startswith("Bearer "):
            token = token[7:]

        from api.middleware.auth import verify_jwt_token, jwt_config
        try:
            user_data = verify_jwt_token(
                token,
                jwt_config.public_key,
                jwt_config.issuer,
                jwt_config.audience,
            )
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Authentication failed: {e}"
            })
            await websocket.close(code=4003, reason="Auth failed")
            return

        user_id = int(user_data.get("user_ID", 0))
        await websocket.send_json({"type": "auth_ok", "userId": user_id})
        logger.info("WebSocket: Authenticated user %d", user_id)

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "chat":
                if chat_task and not chat_task.done():
                    chat_task.cancel()
                    try:
                        await chat_task
                    except (asyncio.CancelledError, Exception):
                        pass

                chat_task = asyncio.create_task(
                    _handle_chat(websocket, data, user_id, user_data)
                )

            elif msg_type == "tool_result":
                _route_tool_result(websocket, data)

            elif msg_type == "tool_error":
                _route_tool_error(websocket, data)

            elif msg_type == "approval_response":
                from core.approvals import resolve_approval
                resolve_approval(
                    data.get("approvalId", ""),
                    bool(data.get("approved", False)),
                    user_id=user_id,
                    reason=data.get("reason", ""),
                )

            elif msg_type == "stop":
                if chat_task and not chat_task.done():
                    chat_task.cancel()
                    try:
                        await chat_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    await websocket.send_json({"type": "event", "event": "done"})
                logger.info("WebSocket: Stop requested by client")

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                logger.warning("WebSocket: Unknown message type: %s", msg_type)

    except WebSocketDisconnect:
        logger.info("WebSocket: Client disconnected")
    except asyncio.TimeoutError:
        logger.warning("WebSocket: Auth timeout")
        try:
            await websocket.close(code=4008, reason="Auth timeout")
        except Exception:
            pass
    except Exception as e:
        logger.error("WebSocket: Error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        if chat_task and not chat_task.done():
            chat_task.cancel()
            try:
                await chat_task
            except (asyncio.CancelledError, Exception):
                pass
        executor = _active_executors.pop(id(websocket), None)
        if executor:
            executor.cancel_all()


def _route_tool_result(websocket: WebSocket, data: dict):
    """Route an incoming tool_result to the correct RemoteToolExecutor."""
    executor = _active_executors.get(id(websocket))
    if executor:
        executor.resolve_result(
            data.get("requestId", ""),
            data.get("result", "")
        )
    else:
        logger.warning("WebSocket: tool_result but no active executor")


def _route_tool_error(websocket: WebSocket, data: dict):
    """Route an incoming tool_error to the correct RemoteToolExecutor."""
    executor = _active_executors.get(id(websocket))
    if executor:
        executor.resolve_error(
            data.get("requestId", ""),
            data.get("error", "Unknown error")
        )


async def _handle_chat(
    websocket: WebSocket,
    data: dict,
    user_id: int,
    user_data: dict,
):
    """Handle a chat message — runs the full agent loop with bidirectional tool execution.
    
    This runs as a BACKGROUND TASK so the main WebSocket message loop
    can continue receiving tool_result messages concurrently.
    """
    from api.services.chat_service import ChatService
    from core.tool_executor import RemoteToolExecutor

    message = data.get("message", "")
    conversation_id = data.get("conversationId")
    context = data.get("context", {})
    attachments_in = data.get("attachments") or []

    if not message and not attachments_in:
        await websocket.send_json({"type": "error", "message": "Empty message"})
        return

    if context:
        ctx_block = "\n\n<agent_context>\n"
        if context.get("workspaceRoot"):
            ctx_block += f"[Workspace Root: {context['workspaceRoot']}]\n"
        ctx_block += ("[Mode: Local — file tools (view_file, list_dir, grep_search, "
                      "write_to_file, run_command) run on the USER'S machine against "
                      "the workspace above. Use them to read/edit the user's real files.]\n")
        if context.get("openFiles"):
            ctx_block += "[Open Files:]\n"
            for f in context["openFiles"]:
                ctx_block += f"- {f}\n"
        if context.get("activeFile"):
            ctx_block += f"\n[Active File: {context['activeFile']}]\n"
        if context.get("activeFileContent"):
            trunc = " (truncated)" if context.get("activeFileTruncated") else ""
            ctx_block += (f"[Active File Content{trunc}:]\n```\n"
                          f"{context['activeFileContent']}\n```\n")
        if context.get("selectedText"):
            ctx_block += (f"[Selected Text in {context.get('activeFile', 'active file')}:]\n"
                          f"```\n{context['selectedText']}\n```\n")
        ctx_block += "</agent_context>\n"
        message = message + ctx_block

    app = websocket.app
    svc: ChatService = app.state.chat_service

    # Inline attachments (base64 over the authed socket) → store via the file
    # service and pass file ids to stream_chat (same path as the web upload).
    attachment_ids = []
    if attachments_in:
        import base64 as _b64
        fsvc = getattr(app.state, "file_service", None)
        for a in attachments_in:
            try:
                raw = _b64.b64decode(a.get("dataB64") or a.get("data") or "")
                mt = a.get("mediaType") or "application/octet-stream"
                if not raw or (fsvc and fsvc.validate(len(raw), mt)):
                    continue
                res = fsvc.save_upload(data=raw, filename=a.get("fileName") or "file",
                                       mime_type=mt, user_id=user_id)
                attachment_ids.append(res["fileId"])
            except Exception:
                logger.warning("WebSocket: attachment upload failed", exc_info=True)

    try:
        conv = svc.get_or_create_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            source="vscode",
        )
        conversation_id = conv["conversation_id"]

        from api.services.chat_service import _session_pool
        _session_pool._ensure_cli()
        tool_registry = _session_pool._cli.tool_registry

        remote_executor = RemoteToolExecutor(websocket, tool_registry)
        _active_executors[id(websocket)] = remote_executor

        try:
            ws_app_id = user_data.get("app_id")
            async for event_str in svc.stream_chat(
                conversation_id=conversation_id,
                user_message=message or " ",
                user_id=user_id,
                app_id=int(ws_app_id) if ws_app_id is not None else None,
                tool_executor=remote_executor,
                page_nav=context.get("nav") if isinstance(context, dict) else None,
                attachment_ids=attachment_ids or None,
            ):
                for line in event_str.strip().split("\n"):
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        await websocket.send_json({"type": "event", "event": "done"})
                        break
                    try:
                        payload = json.loads(raw)
                        await websocket.send_json({
                            "type": "event",
                            **payload,
                        })
                    except json.JSONDecodeError:
                        pass

        finally:
            remote_executor.cancel_all()
            _active_executors.pop(id(websocket), None)

    except asyncio.CancelledError:
        logger.info("WebSocket chat cancelled (user stop)")
        raise
    except Exception as e:
        logger.error("WebSocket chat error: %s", e, exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass
