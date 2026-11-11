"""
Service Chat Router — the server-to-server chat surface.
═══════════════════════════════════════════════════════════════════════════
Auth: X-API-Key: ag_sk_live_…   (api/middleware/api_key_auth.py)

  POST   /v1/service/files                           → upload an attachment
  POST   /v1/service/chat                            → SSE stream
  GET    /v1/service/conversations                   → this end user's threads
  GET    /v1/service/conversations/{id}/messages     → one thread's history
  DELETE /v1/service/conversations/{id}              → forget a thread
  GET    /v1/service/whoami                          → what this key resolves to

── The one idea this router is built on ────────────────────────────────────
A service conversation is owned by (key, end user) — never by a conversation
id alone. The caller is a BACKEND holding one credential on behalf of many of
its own users, so "does this key hold the conversation id?" is not an
ownership question: it would let one learner fetch another learner's lesson by
guessing a uuid, and PrepCrest's are children's transcripts. Every read below
therefore filters on both columns, which is exactly the mistake the bot token's
GET /v1/bot/history/{sessionId} makes and why that credential could not carry
this. See V040_service_api_keys.sql.

── Why endUserRef is required, not optional ────────────────────────────────
It is the ownership key and the rate-limit bucket. Defaulting it (to "anon",
say) would silently collapse every one of the caller's users into one shared
thread and one shared bucket — quietly wrong in exactly the way that is hardest
to notice from the calling side, because it still returns 200s.

── Why the conversation id cannot be caller-chosen ─────────────────────────
POST with no conversationId MINTS one and returns it; POST with one RESOLVES
it or 404s. A caller-supplied id for a row that does not exist is never
created: ids are global, so honouring that would let one backend squat an id
another caller is about to be given, and the collision would surface as someone
else's messages. The caller stores what we hand back — for PrepCrest that is
the tutor session → agent conversation mapping.

── Why a service key can upload, and what that means for ownership ─────────
Without POST /v1/service/files a backend cannot put a picture in front of a
model at all: /v1/files requires a user JWT, and no tool reads an image. So a
vision persona was reachable from the browser chat and from nowhere else,
which made "look at these photographs and tell me which one depicts the word"
a thing this platform could describe and not do.

Ownership of an uploaded file is the KEY, not the end user, and that is
deliberate rather than an oversight. ag_system.files.created_by holds the key's
service_user_id, so assign_files' `created_by = user_id` filter scopes an
attachment to the calling backend. It does NOT scope it to one endUserRef —
because a service key's file ids are minted by the backend itself, never handed
to its end users, so there is no untrusted party to protect them from. A
backend that does expose ids to its own users is responsible for that boundary
in the same way it is for its own database rows.
"""
import logging
import uuid
from typing import Dict, List, Optional

from fastapi import (
    APIRouter, Depends, File, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.middleware.api_key_auth import (
    rate_limit_session_key, require_scope, require_service_key,
)

logger = logging.getLogger("agent.service.chat")

router = APIRouter(prefix="/v1/service", tags=["Service API"])

# An end_user_ref is the caller's own identifier, opaque to us — a database id,
# a uuid, a hash. Bounded only to keep an unbounded string out of an indexed
# column and out of the Redis key it becomes.
MAX_END_USER_REF = 200

# Attachments per turn. Bounded because every one becomes a base64 block in the
# provider request: eight photographs is already a large payload, and a caller
# that sends fifty does not get a better answer — it gets a 413 from the
# provider, several seconds after we accepted the turn.
MAX_ATTACHMENTS = 8


class ServiceChatRequest(BaseModel):
    """One turn, on behalf of one of the caller's end users."""

    message: str = Field(..., min_length=1, max_length=32000,
                         description="The end user's message.")
    end_user_ref: str = Field(..., alias="endUserRef", min_length=1,
                              max_length=MAX_END_USER_REF,
                              description="YOUR id for this end user. Opaque to "
                                          "us; scopes the conversation and the "
                                          "rate-limit bucket.")
    conversation_id: Optional[str] = Field(
        None, alias="conversationId",
        description="Continue a thread. Omit to start one — the id comes back "
                    "on message.start and message.end; store it.")
    model: Optional[str] = Field(
        None, description="Override the profile's model for this turn.")
    title: Optional[str] = Field(
        None, max_length=200,
        description="Title for a NEW conversation. Ignored when continuing.")
    attachment_ids: Optional[List[int]] = Field(
        None, alias="attachmentIds", max_length=MAX_ATTACHMENTS,
        description="File ids from POST /v1/service/files, attached to THIS "
                    "turn. Images are sent to the model as a bounded vision "
                    "variant; anything the selected model cannot see is "
                    "ignored by the provider layer, not by us.")

    class Config:
        populate_by_name = True


def _chat_repo(request: Request):
    # Built per request off app.state.db so it resolves to the caller's tenant
    # database — same construction as every other repository on this API.
    from api.repositories.chat_repo import ChatRepository

    return ChatRepository(request.app.state.db)


def _clean_ref(end_user_ref: str) -> str:
    ref = (end_user_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=422, detail="endUserRef must not be blank.")
    if len(ref) > MAX_END_USER_REF:
        raise HTTPException(
            status_code=422,
            detail=f"endUserRef exceeds {MAX_END_USER_REF} characters.")
    return ref


def _enforce_rate_limit(principal: Dict, end_user_ref: str) -> None:
    """Per END USER — never per key and never per IP.

    Both of the obvious buckets are the same mistake: a backend is one address
    holding one key in front of all of its users, so either choice puts every
    end user in one bucket and lets the busiest starve the rest. That is the
    concrete reason the bot token's 30/IP/hour could not carry this, and
    limiting per key would have rebuilt it one level up.

    EmbedRateLimiter and not something local: this API runs multiple workers,
    so an in-process cap of N is really N × workers — silently wrong, and wrong
    in the permissive direction.
    """
    from api.services.rate_limiter import embed_rate_limiter

    session_key = rate_limit_session_key(principal["key_id"], end_user_ref)
    allowed, reason = embed_rate_limiter.check(
        integration_id=principal["key_id"],
        session_id=session_key,
        # Empty on purpose. rate_limits.per_ip_per_min defaults to 0 (disabled)
        # for a service key; passing the address anyway would arm the dimension
        # for anyone who set it without understanding it.
        client_ip="",
        rate_limits=principal.get("rate_limits") or {},
    )
    if not allowed:
        # A real 429, not the widget's SSE error frame. The caller here is a
        # backend with retry logic, and a status code is something it can act
        # on without parsing a stream body.
        raise HTTPException(
            status_code=429, detail=reason or "Rate limit exceeded.",
            headers={"Retry-After": "60"},
        )
    embed_rate_limiter.record_message(session_key, "")


def _resolve_conversation(repo, principal: Dict, end_user_ref: str,
                          conversation_id: Optional[str],
                          title: str = "") -> str:
    """Find the caller's thread, or start one. Never adopts an unknown id."""
    key_id = principal["key_id"]

    if conversation_id:
        row = repo.get_service_conversation(
            conversation_id, service_key_id=key_id, end_user_ref=end_user_ref)
        if not row:
            # 404 and not 403: whether the id exists under a different owner is
            # not this caller's business, and answering it would turn the
            # endpoint into a probe for other backends' conversation ids.
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return conversation_id

    new_id = str(uuid.uuid4())
    repo.create_service_conversation(
        new_id,
        service_key_id=key_id,
        end_user_ref=end_user_ref,
        # A real user row — the key's service_user_id — so llm_scope budgets,
        # the token ledger and the dashboards keep working with no notion of
        # "service" at all.
        user_id=principal["user_ID"],
        title=(title or "")[:200],
    )
    logger.info("service conversation opened: key=%s end_user=%s conv=%s",
                key_id, end_user_ref, new_id[:8])
    return new_id


@router.post(
    "/chat",
    summary="Send a message on behalf of an end user — SSE streaming response",
    description="""
Send one turn to the agent and receive the reply as Server-Sent Events.

**Required header:** `X-API-Key: ag_sk_live_…`
(`Authorization: ApiKey ag_sk_live_…` is accepted too.)

**Conversation lifecycle**
Omit `conversationId` to start a thread — the id arrives on `message.start`
and `message.end`. Store it and send it back to continue. The thread is scoped
to `(key, endUserRef)`: another end user cannot read it even with the id.

**Event types**
`message.start` · `status` · `message.delta` · `tool.start` / `tool.end` ·
`artifact` · `message.end` · `error` · `ping` · `[DONE]`

`artifact` carries media the model GENERATED — `{fileId, kind, mediaType}`. The
bytes are not on the stream: fetch them from `GET /media/{fileId}`. It was
always emitted (the service path shares `stream_agent_turn` with the chat UI)
and merely undocumented here, which is worse than absent — a caller reading this
list has no reason to write a handler, so a generated image reaches them as a
sentence about a picture they never receive.

**Usage accounting on `message.end`**
- `conversationTokens` / `conversationCostUsd` — CUMULATIVE for the thread, not
  for this turn. There is no per-turn pair: `final_usage_fields` emits these two
  and nothing else, and a caller that reads them as the turn's own cost
  overstates every turn after the first, and does so more the longer the thread
  runs.

  To bill a turn, take the delta from the previous reading. To bill a JOB, open
  a fresh conversation for it — then the cumulative figure IS the job's cost,
  which is what a batch caller usually wants.

**Persona**
Fixed by the key (its pinned persona, else the application's default). The
`system_prompt` parameter is deliberately not exposed: the persona is the
system prompt and a caller may not override it. Per-turn context belongs in the
message body.

**Rate limiting**
Per end user, from the key's `rate_limits.per_session_msg` (default 120/hour).
Exceeded returns HTTP **429** with `Retry-After`.

```
curl -N -H "X-API-Key: ag_sk_live_…" \\
     -H "Content-Type: application/json" \\
     -d '{"message":"explain quadratics","endUserRef":"learner_4821"}' \\
     https://…/api/v1/service/chat
```
""",
)
async def service_chat(
    chat_request: ServiceChatRequest,
    request: Request,
    principal: Dict = Depends(require_service_key),
):
    require_scope(principal, "chat")
    end_user_ref = _clean_ref(chat_request.end_user_ref)

    # Order matters: refuse before spending. The limit check comes before the
    # conversation is created so a throttled caller does not leave a trail of
    # empty threads behind.
    _enforce_rate_limit(principal, end_user_ref)

    repo = _chat_repo(request)
    conversation_id = _resolve_conversation(
        repo, principal, end_user_ref,
        chat_request.conversation_id, chat_request.title or "")

    svc = request.app.state.chat_service

    # Logged because an attachment that does not arrive is otherwise INVISIBLE
    # from both ends: the caller sent ids and got a 200, and the model answers
    # about pictures it never received. One line here is the difference between
    # "the vision channel is broken" and "the model is bad at this".
    logger.info("service chat: key=%s conv=%s attachments=%s",
                principal["key_id"], conversation_id[:8],
                chat_request.attachment_ids or [])

    return StreamingResponse(
        svc.stream_chat(
            conversation_id=conversation_id,
            user_message=chat_request.message,
            user_id=principal["user_ID"],
            model=chat_request.model,
            app_id=principal["app_id"],
            user_role="service",
            # The key's own provider credential, if it has one (V058). Only
            # api_key is overridden; the model is still the application's.
            llm_api_key=principal.get("llm_api_key"),
            # Pinned by the key. apply_persona owns the precedence rule
            # (embed > explicit > app default) — this only supplies the
            # explicit one and must not second-guess it.
            persona_id=principal.get("persona_id"),
            # Bound to the message inside stream_chat, filtered on
            # created_by = this key's service user. An id belonging to another
            # key updates no rows and is silently not attached, which is the
            # same answer routers/chat.py gives a cross-user id.
            attachment_ids=chat_request.attachment_ids,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # No Access-Control-Allow-Origin. The bot widget needs one because
            # it is fetched from a page; a backend is not a browser, and
            # echoing "*" onto an authenticated stream is a habit worth not
            # forming.
        },
    )


@router.post(
    "/files",
    summary="Upload an attachment for a later turn",
    description="""
Store one file and get back its `fileId`. Pass that id in `attachmentIds` on a
subsequent `POST /v1/service/chat` to put it in front of the model.

**Required header:** `X-API-Key: ag_sk_live_…`

Two calls rather than one multipart chat request, mirroring `/v1/files`: the
same picture is frequently sent to several turns — a candidate photograph judged
against one word and then against a sibling set — and uploading it once means
one copy on disk and one base64 encoding, not one per turn.

An image is stored with a bounded **vision variant** beside it, and that variant
is what reaches the model. The original is kept for serving.
""",
)
async def upload_service_file(
    request: Request,
    file: UploadFile = File(...),
    principal: Dict = Depends(require_service_key),
) -> Dict:
    # The same 'chat' scope rather than a new one. Uploading is half of sending a
    # message and has no use on its own, so a separate scope would only mean
    # every already-minted key needs re-scoping before it can send a picture —
    # an upgrade step whose failure mode is a 403 nobody expects.
    require_scope(principal, "chat")

    svc = request.app.state.file_service
    user_id = principal["user_ID"]

    data = await file.read()
    media_type = file.content_type or "application/octet-stream"

    # Size and type are the file service's rules, not this router's. A second
    # copy of the allow-list here is a second thing to forget when a provider
    # starts accepting a new format — and the two would disagree silently, in
    # the direction of accepting something the model cannot read.
    err = svc.validate(len(data), media_type)
    if err:
        raise HTTPException(status_code=400, detail=err)

    try:
        stored = svc.save_upload(
            data=data, filename=file.filename or "attachment",
            mime_type=media_type, user_id=user_id)
    except Exception:
        logger.exception("service attachment upload failed for key=%s",
                         principal["key_id"])
        raise HTTPException(
            status_code=500, detail="Could not store the file. Please try again.")

    logger.info("service upload: key=%s file=%s %s %s bytes",
                principal["key_id"], stored.get("fileId"),
                media_type, stored.get("size"))
    return stored


@router.get(
    "/conversations",
    summary="List an end user's conversations",
    description="Scoped to `(key, endUserRef)`. Returns only threads this key "
                "opened for this end user.",
)
async def list_service_conversations(
    request: Request,
    end_user_ref: str = Query(..., alias="endUserRef"),
    limit: int = Query(50, ge=1, le=200),
    principal: Dict = Depends(require_service_key),
) -> List[Dict]:
    require_scope(principal, "chat")
    ref = _clean_ref(end_user_ref)
    return _chat_repo(request).list_service_conversations(
        service_key_id=principal["key_id"], end_user_ref=ref, limit=limit)


@router.get(
    "/conversations/{conversation_id}/messages",
    summary="Read one conversation's history",
    description="Ownership is re-checked on `(key, endUserRef)` before any "
                "message is read — holding the id is not sufficient.",
)
async def get_service_messages(
    conversation_id: str,
    request: Request,
    end_user_ref: str = Query(..., alias="endUserRef"),
    limit: int = Query(100, ge=1, le=500),
    principal: Dict = Depends(require_service_key),
) -> List[Dict]:
    require_scope(principal, "chat")
    ref = _clean_ref(end_user_ref)
    repo = _chat_repo(request)

    # The ownership check is a separate read on purpose: get_messages() takes a
    # conversation id and nothing else, so it can never enforce this itself.
    owned = repo.get_service_conversation(
        conversation_id, service_key_id=principal["key_id"], end_user_ref=ref)
    if not owned:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return repo.get_messages(conversation_id, limit=limit)


@router.delete(
    "/conversations/{conversation_id}",
    summary="Delete a conversation",
    description="Removes the thread and its messages. Scoped to "
                "`(key, endUserRef)` like every other read here.",
)
async def delete_service_conversation(
    conversation_id: str,
    request: Request,
    end_user_ref: str = Query(..., alias="endUserRef"),
    principal: Dict = Depends(require_service_key),
) -> Dict:
    require_scope(principal, "chat")
    ref = _clean_ref(end_user_ref)

    deleted = _chat_repo(request).delete_service_conversation(
        conversation_id, service_key_id=principal["key_id"], end_user_ref=ref)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    logger.info("service conversation deleted: key=%s end_user=%s conv=%s",
                principal["key_id"], ref, conversation_id[:8])
    return {"deleted": True, "conversationId": conversation_id}


@router.get(
    "/whoami",
    summary="What this key resolves to",
    description="Cheap credential check for a caller wiring up configuration — "
                "confirms the key is live and shows the application and persona "
                "it is bound to. Never returns the key or its hash.",
)
async def service_whoami(principal: Dict = Depends(require_service_key)) -> Dict:
    return {
        "keyId": principal["key_id"],
        "keyName": principal.get("key_name") or "",
        "appId": principal["app_id"],
        "personaId": principal.get("persona_id"),
        "scopes": principal.get("scopes") or [],
        "rateLimits": principal.get("rate_limits") or {},
        "sourceIp": principal.get("source_ip") or "",
    }
