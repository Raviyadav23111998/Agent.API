"""
Embed WebSocket — the unified runtime for embedded chat + copilot (Phase 2).
═══════════════════════════════════════════════════════════════════════════
One bidirectional WS for both modes. Auth is folded into the upgrade (D9):

  client → {type:'auth', key:'ag_pk_…', origin?, identity?}
  server → {type:'auth_ok', mode}              (or {type:'error'} + close)
  client → {type:'chat', message, conversationId?}
  server → {type:'event', event:'message.delta'|'tool.start'|…}
  server → {type:'tool_request', …}  (copilot: page tools run in the browser)
  client → {type:'tool_result'|'tool_error', …}

The session runs a SANDBOXED agent (integration persona ∩ embed-safe tools),
streams the answer (thinking hidden — customer-facing), and for copilot routes
page_* tools to the embedded page via RemoteToolExecutor.
"""
import asyncio
import logging
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("agent.embed")
router = APIRouter(tags=["Embed"])

_embed_executors: Dict[int, "object"] = {}


@router.websocket("/v1/embed/ws")
async def embed_ws(websocket: WebSocket):
    await websocket.accept()
    chat_task: Optional[asyncio.Task] = None
    claims: Optional[dict] = None

    try:
        auth = await asyncio.wait_for(websocket.receive_json(), timeout=30)
        if auth.get("type") != "auth":
            await websocket.send_json({"type": "error", "message": "first frame must be auth"})
            await websocket.close(code=4001)
            return

        from api.services.embed_session_auth import EmbedSessionAuth
        origin = (websocket.headers.get("origin")
                  or websocket.headers.get("referer")
                  or auth.get("origin") or "")
        _, claims, err = EmbedSessionAuth(websocket.app.state.db).handshake(
            auth.get("key", ""), origin, auth.get("identity"))
        if err:
            await websocket.send_json({"type": "error", "message": err})
            await websocket.close(code=4003)
            return

        client_session = auth.get("sessionId") or f"ws{id(websocket)}"
        claims["conv_id"] = (
            f"embed_{claims['integration_id']}_"
            f"{claims.get('end_user_id') or client_session}"
        )

        gp = claims.get("guardrail_policy") or {}
        egress_redact = gp.get("egress_redact", claims["mode"] == "copilot")

        claims["_client_mode"] = claims["mode"]
        await websocket.send_json({
            "type": "auth_ok",
            "mode": claims["mode"],
            "egressRedact": egress_redact,
        })
        logger.info("Embed WS: integration %s (%s) from %s (egressRedact=%s)",
                    claims["integration_id"], claims["mode"], origin, egress_redact)

        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")

            if mtype == "chat":
                from api.services.rate_limiter import embed_rate_limiter
                client_ip = websocket.client.host if websocket.client else ""
                rl_ok, rl_reason = embed_rate_limiter.check(
                    claims["integration_id"],
                    claims["conv_id"],
                    client_ip, claims.get("rate_limits"),
                )
                if not rl_ok:
                    await websocket.send_json({"type": "error", "message": rl_reason})
                    continue
                tok_ok, tok_reason = embed_rate_limiter.check_daily_tokens(
                    claims["integration_id"], claims.get("rate_limits"))
                if not tok_ok:
                    await websocket.send_json({"type": "error", "message": tok_reason})
                    continue
                embed_rate_limiter.record_message(
                    claims["conv_id"], client_ip)

                if chat_task and not chat_task.done():
                    chat_task.cancel()
                    try:
                        await chat_task
                    except (asyncio.CancelledError, Exception):
                        pass
                chat_task = asyncio.create_task(_handle_embed_chat(websocket, data, claims))

            elif mtype == "tool_result":
                ex = _embed_executors.get(id(websocket))
                if ex:
                    ex.resolve_result(data.get("requestId", ""), data.get("result", ""))

            elif mtype == "tool_error":
                ex = _embed_executors.get(id(websocket))
                if ex:
                    ex.resolve_error(data.get("requestId", ""), data.get("error", "error"))

            elif mtype == "approval_response":
                from core.approvals import resolve_approval
                resolve_approval(data.get("approvalId", ""), bool(data.get("approved", False)))

            elif mtype == "stop":
                if chat_task and not chat_task.done():
                    chat_task.cancel()
                    try:
                        await chat_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    await websocket.send_json({"type": "event", "event": "done"})

            elif mtype == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Embed WS: disconnected")
    except asyncio.TimeoutError:
        try:
            await websocket.close(code=4008, reason="auth timeout")
        except Exception:
            pass
    except Exception as e:
        logger.error("Embed WS error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": "internal error"})
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if chat_task and not chat_task.done():
            chat_task.cancel()
            try:
                await chat_task
            except (asyncio.CancelledError, Exception):
                pass
        ex = _embed_executors.pop(id(websocket), None)
        if ex:
            ex.cancel_all()
        if claims:
            try:
                from api.services.rate_limiter import embed_rate_limiter
                embed_rate_limiter.cleanup_session(
                    claims["conv_id"])
            except Exception:
                pass


async def _handle_embed_chat(websocket: WebSocket, data: dict, claims: dict):
    message = (data.get("message") or "").strip()
    if not message:
        await websocket.send_json({"type": "error", "message": "empty message"})
        return

    from api.services.chat_service import _session_pool
    from api.services.agent_streamer import stream_agent_turn, final_usage_fields
    from core.tool_executor import RemoteToolExecutor

    _session_pool._ensure_cli()

    from api.services.embed_session_auth import EmbedSessionAuth
    ok, refresh_err = EmbedSessionAuth(websocket.app.state.db).refresh_claims(claims)
    if not ok:
        await websocket.send_json({"type": "error", "message": refresh_err or "integration unavailable"})
        return

    if claims.get("mode") != claims.get("_client_mode"):
        gp = claims.get("guardrail_policy") or {}
        egress_redact = gp.get("egress_redact", claims["mode"] == "copilot")
        await websocket.send_json({
            "type": "mode", "mode": claims["mode"], "egressRedact": egress_redact,
        })
        logger.info("Embed WS: mode switched %s → %s (integration %s)",
                    claims.get("_client_mode"), claims["mode"], claims["integration_id"])
        claims["_client_mode"] = claims["mode"]

    integration_id = claims["integration_id"]
    conv_id = claims["conv_id"]

    from core.embed_sandbox import embed_safe_tools
    from core.tool_executor import LOCAL_TOOLS as _LOCAL_TOOLS
    allowed_local = embed_safe_tools(claims["mode"]) & _LOCAL_TOOLS
    remote = RemoteToolExecutor(
        websocket, _session_pool._cli.tool_registry,
        allowed_local_tools=allowed_local)
    _embed_executors[id(websocket)] = remote

    session = await _session_pool.get_session(
        conversation_id=conv_id,
        user_id=0,
        app_id=claims.get("app_id"),
        tool_executor=remote,
        page_nav=(data.get("context") or {}).get("nav"),
        embed={
            "mode": claims["mode"],
            "persona_id": claims.get("persona_id"),
            "integration_id": integration_id,
            "guardrail_policy": claims.get("guardrail_policy") or {},
            "end_user": conv_id,
            "site": claims.get("origin") or "",
        },
    )

    # Execute only what this session was offered (sandboxed registry), never
    # the full server registry the executor was constructed with.
    remote.restrict_to(getattr(session.agent, "tool_registry", None))

    def _frame(event: str, **kw):
        return {"type": "event", "event": event, **kw}

    try:
        await websocket.send_json(_frame("message.start", conversationId=conv_id))
        state = {"final_text": ""}
        async for frame in stream_agent_turn(
                session.agent, message, _frame, state,
                timeout_s=300, ping_every=15, include_thinking=False):
            await websocket.send_json(frame)
        await websocket.send_json(_frame(
            "message.end", content=state["final_text"], **final_usage_fields(session.agent)))
        await websocket.send_json({"type": "event", "event": "done"})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Embed chat error: %s", e, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": "agent error"})
        except Exception:
            pass
    finally:
        remote.cancel_all()
        _embed_executors.pop(id(websocket), None)
