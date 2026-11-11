"""
Integrations Router — Embed Agent Platform management + session handshake.
═══════════════════════════════════════════════════════════════════════════
  • /v1/integrations …      admin-managed CRUD over embeddable integrations
                            (chat | copilot) — issues publishable + secret keys.
  • POST /v1/embed/session  public handshake: publishable key + Origin → a
                            short-lived scoped session token (Phase 2 folds this
                            into the WS upgrade).

See EMBED_AGENT_PLATFORM_ARCHITECTURE.md Appendix A (#5, #6).
"""
import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.middleware.auth import require_admin
from api.security.embed_keys import mint_publishable, mint_secret
from api.services.embed_session_auth import EmbedSessionAuth

logger = logging.getLogger("agent.embed")
router = APIRouter(tags=["Integrations"])


def _db(request: Request):
    return request.app.state.db


@router.get("/embed.js", include_in_schema=False)
@router.get("/bot/embed.js", include_in_schema=False)
async def serve_embed_js():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "embed.js")
    if not os.path.exists(path):
        raise HTTPException(404, "embed.js not found")
    return FileResponse(path, media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300",
                                 "Access-Control-Allow-Origin": "*"})


class IntegrationCreate(BaseModel):
    name: str
    mode: str = "chat"
    allowed_domains: List[str] = []
    app_id: Optional[int] = None
    persona_id: Optional[int] = None
    welcome_message: Optional[str] = None
    theme_color: Optional[str] = None


class IntegrationPatch(BaseModel):
    name: Optional[str] = None
    mode: Optional[str] = None
    allowed_domains: Optional[List[str]] = None
    app_id: Optional[int] = None
    persona_id: Optional[int] = None
    is_active: Optional[bool] = None


class SessionRequest(BaseModel):
    key: str
    identity: Optional[Dict] = None


@router.post("/v1/integrations", summary="Create an embeddable integration")
async def create_integration(body: IntegrationCreate, request: Request,
                             current_user: Dict = Depends(require_admin)):
    if body.mode not in ("chat", "copilot"):
        raise HTTPException(400, "mode must be 'chat' or 'copilot'")
    from core.security import encrypt_secret

    pk = mint_publishable()
    sk = mint_secret()
    uid = int(current_user.get("user_ID", 0)) or None

    row = _db(request).execute_returning(
        """
        INSERT INTO ag_bot.bots
            (name, api_token, publishable_key, secret_key_enc, mode,
             allowed_domains, app_id, persona_id, welcome_message, theme_color,
             created_by, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        RETURNING bot_id
        """,
        (body.name, f"ag_bot_{pk[6:]}", pk, encrypt_secret(sk), body.mode,
         body.allowed_domains, body.app_id, body.persona_id,
         body.welcome_message, body.theme_color, uid),
    )
    return {
        "integration_id": row["bot_id"],
        "mode": body.mode,
        "publishable_key": pk,
        "secret_key": sk,
        "embed": f'<script src="{str(request.base_url).rstrip("/").replace("/api","")}/bot/embed.js?tenant={request.headers.get("x-tenant-domain") or request.url.hostname}" data-key="{pk}"></script>',
        "note": "Save the secret_key now — it is not retrievable later.",
    }


@router.get("/v1/integrations", summary="List integrations")
async def list_integrations(request: Request, current_user: Dict = Depends(require_admin)):
    rows = _db(request).fetch_all(
        """
        SELECT bot_id AS integration_id, name, mode, publishable_key,
               allowed_domains, app_id, persona_id, is_active,
               (secret_key_enc IS NOT NULL) AS has_secret, created_at
        FROM ag_bot.bots ORDER BY bot_id DESC
        """
    )
    return rows


@router.patch("/v1/integrations/{integration_id}", summary="Update an integration")
async def patch_integration(integration_id: int, body: IntegrationPatch, request: Request,
                            current_user: Dict = Depends(require_admin)):
    fields, params = [], []
    for col in ("name", "mode", "allowed_domains", "app_id", "persona_id", "is_active"):
        val = getattr(body, col)
        if val is not None:
            if col == "mode" and val not in ("chat", "copilot"):
                raise HTTPException(400, "mode must be 'chat' or 'copilot'")
            fields.append(f"{col} = %s")
            params.append(val)
    if not fields:
        raise HTTPException(400, "nothing to update")
    params.append(integration_id)
    n = _db(request).execute(
        f"UPDATE ag_bot.bots SET {', '.join(fields)}, updated_at = NOW() WHERE bot_id = %s",
        tuple(params),
    )
    if not n:
        raise HTTPException(404, "integration not found")
    try:
        from api.services.chat_service import invalidate_config
        invalidate_config(integration_id=integration_id,
                          app_id=getattr(body, "app_id", None))
    except Exception as _e:
        import logging
        logging.getLogger(__name__).warning(
            "integration session invalidation failed: %s", _e)
    return {"updated": True}


@router.post("/v1/integrations/{integration_id}/rotate-keys", summary="Rotate keys")
async def rotate_keys(integration_id: int, request: Request,
                      current_user: Dict = Depends(require_admin)):
    from core.security import encrypt_secret
    pk, sk = mint_publishable(), mint_secret()
    n = _db(request).execute(
        "UPDATE ag_bot.bots SET publishable_key = %s, secret_key_enc = %s, updated_at = NOW() WHERE bot_id = %s",
        (pk, encrypt_secret(sk), integration_id),
    )
    if not n:
        raise HTTPException(404, "integration not found")
    return {"publishable_key": pk, "secret_key": sk, "note": "Old keys are now invalid."}


@router.get("/v1/integrations/{integration_id}/audit",
            summary="Get audit log for an integration")
async def get_audit_log(integration_id: int, request: Request,
                        limit: int = 50, offset: int = 0,
                        current_user: Dict = Depends(require_admin)):
    """Phase 5: audit log viewer — returns recent copilot page actions."""
    from api.services.embed_audit import EmbedAuditRepo
    repo = EmbedAuditRepo(_db(request))
    entries = repo.get_actions(integration_id, limit=min(limit, 200), offset=offset)
    return entries


@router.post("/v1/embed/session", summary="Exchange a publishable key for a session token")
async def embed_session(body: SessionRequest, request: Request):
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    token, claims, err = EmbedSessionAuth(_db(request)).handshake(
        body.key, origin, body.identity)
    if err:
        raise HTTPException(status_code=401, detail=err)
    return {
        "session_token": token,
        "mode": claims["mode"],
        "expires_in_min": EmbedSessionAuth.SESSION_TTL_MIN,
    }
