"""
Agent API — Main Entry Point
═════════════════════════════════════════
≈ SMSystems Program.cs

Architecture:
    1. Bootstrap config from PostgreSQL (ag_system.configs)
    2. Load JWT/RSA keys (shared with SMSystems/Fleet)
    3. Wire repositories → services → routers
    4. Middleware: CORS, tenant context, exception handler
    5. Run FastAPI on port 8100

Usage:
    uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload
"""

import logging
import os
import sys
from typing import Dict

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import path_setup  # noqa: F401 — bootstraps Agent.Core path

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bootstrap → yield → shutdown."""
    logger.info("═" * 50)
    logger.info("  AGENT.API Starting...")
    logger.info("═" * 50)

    from core.config import app_config
    app_config.load()
    logger.info("  Config: %d keys loaded from ag_system.configs", len(app_config._cache))

    from core.tenant_db import TenantDB
    control_db = TenantDB()
    control_db.connect()

    from core.msystem_router import MSystemRouter
    from core.tenant_resolver import TenantConnectionResolver
    from core.tenant_context import multi_tenant_enabled
    try:
        app.state.msystem_router = MSystemRouter()
    except Exception as e:
        app.state.msystem_router = None
        logger.info("  MSystem: router unavailable (%s)", e)
    app.state.tenant_resolver = TenantConnectionResolver(
        msystem_router=app.state.msystem_router)
    from core.tenant_resolver import set_global_resolver
    set_global_resolver(app.state.tenant_resolver)

    if multi_tenant_enabled():
        from core.tenant_db_proxy import TenantDBProxy
        db = TenantDBProxy(app.state.tenant_resolver, control_db)
        logger.info("  Multi-tenant: ON — DB routes per-tenant via MSystem")
    else:
        db = control_db
        logger.info("  Multi-tenant: OFF — single-tenant (control DB only)")
    app.state.control_db = control_db
    app.state.db = db
    logger.info("  Database: connected to %s", app_config.get("db.name", "agent_uat"))

    from api.middleware.auth import load_jwt_config
    load_jwt_config()
    logger.info("  JWT: RSA keys loaded (shared with SMSystems)")

    from api.repositories.user_repo import AuthRepository
    from api.services.auth_service import AuthService
    from api.repositories.user_crud_repo import UserRepository
    from api.services.user_service import UserService
    from api.repositories.chat_repo import ChatRepository
    from api.services.chat_service import ChatService
    from api.repositories.agent_repo import AgentRepository
    from api.services.agent_service import AgentService
    from api.repositories.brain_repo import BrainRepository
    from api.repositories.memory_repo import MemoryRepository
    from api.repositories.bot_repo import BotRepository
    from api.services.bot_service import BotService
    from api.repositories.bot_admin_repo import BotAdminRepository
    from api.services.bot_admin_service import BotAdminService
    from api.repositories.cron_repo import CronRepository
    from api.services.cron_service import CronAdminService
    from api.repositories.app_repo import AppRepository
    from api.services.app_service import AppService
    from api.repositories.system_repo import SystemRepository
    from api.services.system_service import SystemService
    from api.repositories.notification_repo import NotificationRepository
    from api.services.notification_service import NotificationService

    notification_repo = NotificationRepository(db)
    notification_service = NotificationService(notification_repo)
    
    auth_repo = AuthRepository(db)
    auth_service = AuthService(auth_repo)
    user_repo = UserRepository(db)
    user_service = UserService(user_repo, notification_svc=notification_service)
    chat_repo = ChatRepository(db)
    chat_service = ChatService(chat_repo, db)
    from api.repositories.file_repo import FileRepository
    from api.services.file_service import FileService
    file_service = FileService(FileRepository(db), db)
    agent_repo = AgentRepository(db)
    agent_service = AgentService(agent_repo)
    brain_repo = BrainRepository(db)
    memory_repo = MemoryRepository(db)
    bot_repo = BotRepository(db)
    from api.repositories.persona_repo import PersonaRepository
    persona_repo = PersonaRepository(db)
    bot_service = BotService(bot_repo, persona_repo=persona_repo, db=db)
    bot_admin_repo = BotAdminRepository(db)
    bot_admin_service = BotAdminService(bot_admin_repo)
    cron_repo = CronRepository(db)
    cron_admin_service = CronAdminService(cron_repo)
    system_repo = SystemRepository(db)
    system_service = SystemService(system_repo)

    from api.repositories.dashboard_repo import DashboardRepository
    from api.services.dashboard_service import DashboardService
    from api.repositories.audit_repo import AuditRepository
    from api.services.audit_service import AuditService
    from api.repositories.admin_conversation_repo import AdminConversationRepository
    from api.services.admin_conversation_service import AdminConversationService

    dashboard_repo = DashboardRepository(db)
    dashboard_service = DashboardService(dashboard_repo)
    audit_repo = AuditRepository(db)
    audit_service = AuditService(audit_repo)
    admin_conversation_repo = AdminConversationRepository(db)
    admin_conversation_service = AdminConversationService(admin_conversation_repo)

    app.state.auth_repo = auth_repo
    app.state.auth_service = auth_service
    app.state.user_repo = user_repo
    app.state.user_service = user_service
    app.state.chat_service = chat_service
    app.state.file_service = file_service
    app.state.agent_service = agent_service
    app.state.brain_repo = brain_repo
    app.state.memory_repo = memory_repo
    app.state.bot_service = bot_service
    app.state.bot_admin_repo = bot_admin_repo
    app.state.bot_admin_service = bot_admin_service
    app.state.cron_repo = cron_repo
    app.state.cron_admin_service = cron_admin_service
    app.state.system_repo = system_repo
    app.state.system_service = system_service
    app.state.notification_repo = notification_repo
    app.state.notification_service = notification_service
    app.state.dashboard_repo = dashboard_repo
    app.state.dashboard_service = dashboard_service
    app.state.audit_repo = audit_repo
    app.state.audit_service = audit_service
    app.state.admin_conversation_repo = admin_conversation_repo
    app.state.admin_conversation_service = admin_conversation_service

    app_repo = AppRepository(db)
    app_service = AppService(app_repo, persona_repo=persona_repo)
    app.state.app_repo = app_repo
    app.state.app_service = app_service

    logger.info("  Services: Auth, Users, Chat, Agents, Brain, Memory, Bot, BotAdmin, CronAdmin, Apps, System, Notification, Dashboard, Audit")

    def _on_config_reload(key: str):
        app_config.reload()
        k = (key or "").lower()
        if k == "providers":
            try:
                from core.connections import invalidate_provider_cache
                invalidate_provider_cache()
            except Exception as e:
                logger.warning("  config reload: provider cache invalidate failed (%s)", e)
            return
        if k.startswith(("neo4j", "elasticsearch", "llm.embedding")):
            try:
                from api.services.chat_service import _refresh_integrations_local
                _refresh_integrations_local()
            except Exception as e:
                logger.warning("  config reload: integration refresh failed (%s)", e)
    try:
        from core.redis_client import subscribe_config_reload
        subscribe_config_reload(_on_config_reload)
        logger.info("  Redis: config reload subscriber started")
    except Exception as e:
        logger.info("  Redis: config reload subscriber skipped (%s)", e)

    try:
        from api.services.chat_service import start_session_invalidation_subscriber
        start_session_invalidation_subscriber()
        logger.info("  Redis: session invalidation subscriber started")
    except Exception as e:
        logger.info("  Redis: session invalidation subscriber skipped (%s)", e)

    logger.info("═" * 50)
    logger.info("  AGENT.API Ready — Port 8100")
    logger.info("  Swagger: http://localhost:8100/swagger")
    logger.info("═" * 50)

    yield

    if hasattr(app.state, 'tenant_resolver'):
        try:
            app.state.tenant_resolver.close_all()
        except Exception:
            pass
    if hasattr(app.state, 'control_db'):
        app.state.control_db.close()
    elif hasattr(app.state, 'db'):
        app.state.db.close()
    logger.info("AGENT.API Shutdown")


# M5 — do not expose the interactive API docs / full OpenAPI schema publicly
# in production. Derived from the environment (AG_ENV, else the DB name suffix
# in AG_DATABASE_URL). uat/sit keep the docs for development.
_dsn = os.environ.get("AG_DATABASE_URL", "")
_env = (os.environ.get("AG_ENV")
        or (_dsn.rsplit("/", 1)[-1].split("_")[-1] if "_" in _dsn else "")).lower()
_IS_PROD = _env == "prod"

app = FastAPI(
    title="AGENT.API",
    description="Agent API — AI Agent System for Storeglance Platform",
    version="1.0.0",
    docs_url=None if _IS_PROD else "/swagger",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
    lifespan=lifespan,
)

logger = logging.getLogger("agent.api")
from core.obs_logging import setup_structured_logging
setup_structured_logging(app="agent")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # This is a BEARER-TOKEN API (Authorization header), not cookie-based —
    # so credentials mode is not needed, and turning it OFF is what makes
    # allow_origins="*" safe: a caller must already hold a valid token, and
    # no cross-origin site can ride the user's ambient credentials. The
    # previous ["*"] + allow_credentials=True combination made Starlette
    # reflect ANY origin with Access-Control-Allow-Credentials: true, which
    # is the dangerous configuration. Tenants use arbitrary custom domains,
    # so a static origin allowlist is impractical; dropping credentials is
    # the correct fix for a token API.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["content-disposition"],
)

from api.middleware.tenant import TenantResolutionMiddleware
app.add_middleware(TenantResolutionMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path,
                 exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred. Please try again later.",
            "statusCode": 500,
        },
    )


# M2 — unify the error contract. HTTPExceptions raised across the code base
# otherwise return FastAPI's default {"detail": ...}, while the two handlers
# above return {error, message, statusCode}. Normalize ALL errors to one
# envelope; `detail` is preserved so existing web consumers that read
# `err.error?.detail` keep working (backward-compatible migration).
from starlette.exceptions import HTTPException as _StarletteHTTPException

_STATUS_ERROR_NAME = {
    400: "BadRequest", 401: "Unauthorized", 403: "Forbidden", 404: "NotFound",
    405: "MethodNotAllowed", 409: "Conflict", 413: "PayloadTooLarge",
    415: "UnsupportedMediaType", 422: "ValidationError", 429: "TooManyRequests",
    500: "InternalServerError", 502: "BadGateway", 503: "ServiceUnavailable",
}


@app.exception_handler(_StarletteHTTPException)
async def http_exception_handler(request: Request, exc: _StarletteHTTPException):
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request failed"
    if exc.status_code >= 500:
        logger.error("HTTP %s on %s %s: %s", exc.status_code,
                     request.method, request.url.path, detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _STATUS_ERROR_NAME.get(exc.status_code, "Error"),
            "message": message,
            "statusCode": exc.status_code,
            "detail": detail,  # backward-compat for existing consumers
        },
        headers=getattr(exc, "headers", None),
    )


from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return human-readable validation errors for invalid request bodies."""
    errors = []
    for err in exc.errors():
        field = " → ".join(str(loc) for loc in err.get("loc", []) if loc != "body")
        errors.append({
            "field": field,
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        })
    logger.warning("Validation error on %s %s: %s",
                   request.method, request.url.path, errors)
    return JSONResponse(
        status_code=422,
        content={
            "error": "ValidationError",
            "message": "Request validation failed",
            "statusCode": 422,
            "errors": errors,
        },
    )


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log all requests with method, path, status, and duration."""
    import time as _time
    start = _time.time()
    response = await call_next(request)
    duration_ms = round((_time.time() - start) * 1000, 1)
    path = request.url.path
    if path not in ("/health", "/favicon.ico"):
        logger.info("[%s] %s %s → %d (%sms)",
                    request.client.host if request.client else "-",
                    request.method, path,
                    response.status_code, duration_ms)
    return response


import time as _rl_time
from collections import defaultdict

_login_attempts: Dict[str, list] = defaultdict(list)
_RATE_LIMIT_MAX = 30
_RATE_LIMIT_WINDOW = 60

@app.middleware("http")
async def rate_limit_login(request: Request, call_next):
    """Limit /Login to 10 attempts per IP per minute to prevent brute-force."""
    path = request.url.path.lower()
    if path == "/login" and request.method == "POST":
        client_ip = request.client.host if request.client else "unknown"
        now = _rl_time.time()

        _login_attempts[client_ip] = [
            t for t in _login_attempts[client_ip]
            if now - t < _RATE_LIMIT_WINDOW
        ]

        if len(_login_attempts[client_ip]) >= _RATE_LIMIT_MAX:
            retry_after = int(_RATE_LIMIT_WINDOW - (now - _login_attempts[client_ip][0]))
            logger.warning("Rate limit exceeded for %s on /Login (%d attempts)",
                           client_ip, len(_login_attempts[client_ip]))
            return JSONResponse(
                status_code=429,
                content={
                    "error": "TooManyRequests",
                    "message": f"Too many login attempts. Try again in {retry_after}s.",
                    "statusCode": 429,
                },
                headers={"Retry-After": str(retry_after)},
            )

        _login_attempts[client_ip].append(now)

    return await call_next(request)


from api.routers.health import router as health_router
from api.routers.auth import router as auth_router
from api.routers.user import router as user_router
from api.routers.chat import router as chat_router
from api.routers.files import router as files_router
from api.routers.agent import router as agent_router
from api.routers.brain import router as brain_router
from api.routers.memory import router as memory_router
from api.routers.connections import router as connections_router
from api.routers.api_integrations import router as api_integrations_router
from api.routers.bot import router as bot_router
from api.routers.bot_admin import router as bot_admin_router
from api.routers.service_chat import router as service_chat_router
from api.routers.service_keys_admin import router as service_keys_admin_router
from api.routers.cron_admin import router as cron_admin_router
from api.routers.app_admin import router as app_admin_router
from api.routers.ws import router as ws_router
from api.routers.system import router as system_router
from api.routers.notification import router as notification_router
from api.routers.webhook import router as webhook_router
from api.routers.llm_config import router as llm_config_router
from api.routers.llm_profiles import router as llm_profiles_router
from api.routers.skills import router as skills_router
from api.routers.system_config import router as system_config_router
from api.routers.dashboard import router as dashboard_router
from api.routers.audit import router as audit_router
from api.routers.admin_conversations import router as admin_conversations_router
from api.routers.integrations import router as integrations_router
from api.routers.embed_ws import router as embed_ws_router
from api.routers.tenant_config import router as tenant_config_router
from api.routers.admin_tenant import router as admin_tenant_router
from api.routers.teams_app import router as teams_app_router
from api.routers.vscode_app import router as vscode_app_router
from api.routers.visualstudio_app import router as visualstudio_app_router

app.include_router(health_router)
app.include_router(tenant_config_router)
app.include_router(admin_tenant_router)
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(chat_router)
app.include_router(files_router)
app.include_router(agent_router)
app.include_router(brain_router)
app.include_router(memory_router)
app.include_router(connections_router)
app.include_router(api_integrations_router)
app.include_router(bot_router)
app.include_router(bot_admin_router)
# Server-to-server surface (X-API-Key) + its admin. Additive: no existing route
# changes, and nothing here is reachable until an admin mints a key.
app.include_router(service_chat_router)
app.include_router(service_keys_admin_router)
app.include_router(integrations_router)
app.include_router(embed_ws_router)
app.include_router(cron_admin_router)
app.include_router(app_admin_router)
app.include_router(ws_router)
app.include_router(system_router)
app.include_router(notification_router)
app.include_router(webhook_router)
app.include_router(llm_config_router)
app.include_router(llm_profiles_router)
app.include_router(skills_router)
app.include_router(system_config_router)
app.include_router(dashboard_router)
app.include_router(audit_router)
app.include_router(admin_conversations_router)
app.include_router(teams_app_router)
app.include_router(vscode_app_router)
app.include_router(visualstudio_app_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "AGENT.API",
        "version": "1.0.0",
        "docs": "/swagger",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8100, reload=True)
