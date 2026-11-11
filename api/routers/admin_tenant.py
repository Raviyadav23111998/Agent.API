"""
Admin: tenant store teardown (Multi-Tenancy — agent task A-2)
=============================================================
Service-to-service endpoint that MSystem's offboard handler
(DropAgentDatabaseHandler) calls to tear down the agent's NON-Postgres stores
for a tenant: the Elasticsearch index brain_<sfx> and the Neo4j subgraph.

MSystem owns Postgres teardown (DROP DATABASE/ROLE); the agent owns its own
ES/Neo4j (those live here, not in Postgres). Coordinates are DERIVED from the
tenant id — no per-tenant config needed.

Auth: a shared service token header (X-Service-Token), set on both sides.
Idempotent + best-effort per store.

See MULTITENANT_PROVISIONING_PRODUCTION_PLAN §4.5 / §5.3.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from core.tenant_context import tenant_suffix8

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AdminTenant"])


def _check_service_token(token: Optional[str]):
    import os
    expected = os.environ.get("AG_SERVICE_TOKEN", "")
    if not expected:
        try:
            from core.config import app_config
            expected = (app_config.get_global("secret.service_token") or "").strip()
        except Exception:
            expected = ""
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid or missing service token")


@router.delete("/admin/tenants/{tenant_id}/stores", summary="Tear down a tenant's ES index + Neo4j subgraph")
async def delete_tenant_stores(tenant_id: str,
                               x_service_token: Optional[str] = Header(default=None)):
    _check_service_token(x_service_token)
    sfx = tenant_suffix8(tenant_id)
    result = {"tenant_id": tenant_id, "suffix8": sfx, "elastic": "skipped", "neo4j": "skipped"}

    def _infra(k, d=None):
        try:
            from core.config import app_config
            return app_config.get(k) or d
        except Exception:
            return d

    es_url = _infra("elasticsearch.url")
    if es_url:
        try:
            import urllib.request
            req = urllib.request.Request(f"{es_url.rstrip('/')}/brain_{sfx}", method="DELETE")
            urllib.request.urlopen(req, timeout=10)
            result["elastic"] = f"deleted brain_{sfx}"
        except Exception as e:
            result["elastic"] = f"error: {str(e)[:80]}"
            logger.warning("admin.delete_stores.es_failed: %s", e)

    neo_uri = _infra("neo4j.uri")
    if neo_uri:
        try:
            from brain.storage.graph_store import GraphStore
            g = GraphStore(neo_uri, _infra("neo4j.user", "neo4j"),
                           _infra("neo4j.password", ""), tenant_id=tenant_id)
            g.connect()
            g.delete_tenant()
            g.close()
            result["neo4j"] = "subgraph deleted"
        except Exception as e:
            result["neo4j"] = f"error: {str(e)[:80]}"
            logger.warning("admin.delete_stores.neo4j_failed: %s", e)

    logger.info("admin.tenant_stores_torn_down: %s", result)
    return JSONResponse(result)
