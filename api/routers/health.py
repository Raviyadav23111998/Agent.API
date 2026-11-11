"""
Health Router — System health + metrics endpoints.
"""
import time
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, JSONResponse

from api.schemas.common import HealthResponse

router = APIRouter(tags=["Health"])

_start_time = time.time()


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health(request: Request):
    db_ok = False
    try:
        db = request.app.state.db
        db.fetch_one("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        version="1.0.0",
        service="AGENT.API",
        uptime_seconds=round(time.time() - _start_time, 1),
        db_connected=db_ok,
    )


@router.get("/readyz", summary="Readiness probe (dependency checks)")
async def readyz(request: Request):
    """Readiness probe for orchestrators — fails if a hard dependency is down."""
    checks = {}
    try:
        request.app.state.db.fetch_one("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"down: {str(e)[:80]}"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"ready": ready, "checks": checks},
    )


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
async def metrics():
    """Prometheus text exposition — tokens, cost, latency, tool/LLM rates."""
    from core.telemetry import telemetry
    return PlainTextResponse(telemetry.render_prometheus())


@router.get("/metrics.json", summary="Metrics snapshot (JSON)")
async def metrics_json():
    """JSON metrics snapshot — for dashboards/cost views without Prometheus."""
    from core.telemetry import telemetry
    return telemetry.snapshot()
