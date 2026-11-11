"""
System Config Admin Router — Web-based config management
═════════════════════════════════════════════════════════
Admin-only CRUD for all ag_system.configs entries, with:
  • Grouped response by prefix (llm, agent, brain, memory, etc.)
  • Schema-driven metadata (types, validation, descriptions)
  • Secret masking (is_secret keys → "***…last5")
  • Audit logging for every write
  • Redis pub/sub hot-reload across all processes
  • Source indicators (db | env | default)
"""

import logging
import os
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import get_current_user
from api.schemas.system_config import (
    ConfigBulkUpdateRequest,
    ConfigGroupResponse,
    ConfigItemResponse,
    ConfigUpdateRequest,
)
from core.config import app_config, CONFIG_TO_ENV, DEFAULTS
from core.config_metadata import (
    CONFIG_METADATA,
    GROUP_METADATA,
    validate_config_value,
    get_all_known_keys,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/system-config", tags=["System Config"])


def _is_admin(current_user: dict) -> bool:
    role = current_user.get("role", "member").lower()
    return role in ["admin", "superadmin", "administrator", "owner", "tenant owner"]


def _mask_secret(value: str) -> str:
    """Mask a secret value, showing only the last 5 characters."""
    if not value:
        return ""
    if len(value) <= 5:
        return "*" * len(value)
    return "*" * (len(value) - 5) + value[-5:]


def _resolve_source(key: str) -> str:
    """Determine where the effective value comes from: db, env, or default.

    Resolution order in AppConfig.get() is: DB > ENV > DEFAULTS.
    So if DB has a value, source is always 'db' regardless of env vars.
    """
    if key in app_config._cache and app_config._cache[key]:
        return "db"

    env_var = CONFIG_TO_ENV.get(key)
    if env_var and os.environ.get(env_var):
        return "env"

    return "default"


def _build_config_item(key: str, timestamps: dict = None) -> ConfigItemResponse:
    """Build a ConfigItemResponse for a single key.

    Args:
        timestamps: Pre-loaded dict of {config_key: updated_at_iso} to avoid N+1 queries.
    """
    meta = CONFIG_METADATA.get(key, {})
    is_secret = meta.get("is_secret", False) or app_config.is_secret(key)

    raw_value = app_config.get(key, "")
    display_value = _mask_secret(raw_value) if is_secret and raw_value else (raw_value or "")

    updated_at = timestamps.get(key) if timestamps else None

    return ConfigItemResponse(
        key=key,
        value=display_value,
        is_secret=is_secret,
        description=meta.get("description", ""),
        type=meta.get("type", "text"),
        default=meta.get("default", DEFAULTS.get(key, "")),
        source=_resolve_source(key),
        requires_restart=meta.get("requires_restart", False),
        managed_by=meta.get("managed_by"),
        validation=meta.get("validation"),
        updated_at=updated_at,
    )


@router.get("", response_model=List[ConfigGroupResponse],
            summary="Get all configs grouped by prefix")
async def get_all_configs(
    request: Request,
    current_user: Dict = Depends(get_current_user),
    include_managed: bool = False,
):
    """Get all system configs grouped by prefix with full metadata.

    Args:
        include_managed: If True, include keys that have dedicated settings pages
                         (e.g., llm.model → /settings/llm). Default False (skip them).
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    timestamps = {}
    if app_config.db:
        try:
            rows = app_config.db.fetch_all(
                "SELECT config_key, updated_at FROM ag_system.configs WHERE is_active = TRUE"
            )
            for row in rows:
                if row.get("updated_at"):
                    timestamps[row["config_key"]] = row["updated_at"].isoformat()
        except Exception:
            pass

    all_keys = set(get_all_known_keys())
    for k in app_config._cache.keys():
        all_keys.add(k)

    groups: Dict[str, list] = defaultdict(list)
    for key in sorted(all_keys):
        meta = CONFIG_METADATA.get(key, {})

        if not include_managed and meta.get("managed_by"):
            continue

        group = meta.get("group", key.split(".")[0])
        item = _build_config_item(key, timestamps)
        groups[group].append(item)

    result = []
    for group_key, items in groups.items():
        g_meta = GROUP_METADATA.get(group_key, {})
        result.append(ConfigGroupResponse(
            prefix=group_key,
            label=g_meta.get("label", group_key.title()),
            description=g_meta.get("description", ""),
            icon=g_meta.get("icon", "⚙️"),
            sort=g_meta.get("sort", 99),
            configs=items,
        ))

    result.sort(key=lambda g: g.sort)
    return result


@router.get("/schema", summary="Get config schema/metadata only (no values)")
async def get_config_schema(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Get the config schema for UI rendering — metadata only, no secret values."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    return {
        "groups": GROUP_METADATA,
        "configs": {
            k: {kk: vv for kk, vv in v.items() if kk != "is_secret"}
            for k, v in CONFIG_METADATA.items()
        },
    }


@router.get("/{config_key:path}", response_model=ConfigItemResponse,
            summary="Get a single config value")
async def get_config(
    config_key: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Get a single config value with metadata."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    if (config_key not in CONFIG_METADATA
            and config_key not in app_config._cache
            and config_key not in DEFAULTS):
        raise HTTPException(status_code=404, detail=f"Unknown config key: {config_key}")

    timestamps = {}
    if app_config.db:
        try:
            row = app_config.db.fetch_one(
                "SELECT updated_at FROM ag_system.configs WHERE config_key = %s",
                (config_key,)
            )
            if row and row.get("updated_at"):
                timestamps[config_key] = row["updated_at"].isoformat()
        except Exception:
            pass

    return _build_config_item(config_key, timestamps)


@router.put("", summary="Bulk update multiple configs")
async def bulk_update_configs(
    body: ConfigBulkUpdateRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Update multiple config keys in a single request.

    Validates all values BEFORE writing any — atomic success/failure.
    Publishes a Redis reload signal so all processes pick up changes.
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    user_id = current_user.get("user_ID")

    errors = []
    for update in body.updates:
        if update.value.startswith("*"):
            continue
        is_valid, error = validate_config_value(update.key, update.value)
        if not is_valid:
            errors.append(error)

    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    updated = 0
    for update in body.updates:
        if update.value.startswith("*"):
            continue

        meta = CONFIG_METADATA.get(update.key, {})
        is_secret = meta.get("is_secret", False)

        old_value = app_config.get(update.key, "")
        old_masked = _mask_secret(old_value) if is_secret else old_value

        app_config.set(
            update.key,
            update.value,
            is_secret=is_secret,
            description=update.description,
        )
        updated += 1

        if app_config.db:
            try:
                app_config.db.audit(
                    action="config.update",
                    entity_type="config",
                    entity_id=update.key,
                    user_id=user_id,
                    details={
                        "old": old_masked,
                        "new": _mask_secret(update.value) if is_secret else update.value,
                    },
                )
            except Exception as e:
                logger.error("Audit log failed for config.update: %s", e)

    logger.info("System config: %d keys updated by user %s", updated, user_id)
    return {
        "message": f"Successfully updated {updated} config(s). Changes are live.",
        "updated": updated,
    }


@router.put("/{config_key:path}", summary="Update a single config")
async def update_config(
    config_key: str,
    body: ConfigUpdateRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Update a single config key. The key in the path takes precedence."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    body.key = config_key
    bulk = ConfigBulkUpdateRequest(updates=[body])
    return await bulk_update_configs(bulk, request, current_user)


@router.delete("/{config_key:path}", summary="Deactivate a config key")
async def deactivate_config(
    config_key: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Soft-delete (deactivate) a config key. Sets is_active=FALSE in the DB."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    user_id = current_user.get("user_ID")
    db = app_config.db
    if not db:
        raise HTTPException(status_code=500, detail="Database not available")

    existing = db.fetch_one(
        "SELECT config_id FROM ag_system.configs WHERE config_key = %s",
        (config_key,)
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f"Config key not found: {config_key}")

    db.execute(
        "UPDATE ag_system.configs SET is_active = FALSE, updated_at = NOW() WHERE config_key = %s",
        (config_key,)
    )

    app_config._cache.pop(config_key, None)
    app_config._secrets.discard(config_key)

    try:
        from core.redis_client import publish_config_reload
        publish_config_reload(config_key)
    except Exception:
        pass

    try:
        db.audit(
            action="config.delete",
            entity_type="config",
            entity_id=config_key,
            user_id=user_id,
        )
    except Exception:
        pass

    logger.info("Config '%s' deactivated by user %s", config_key, user_id)
    return {"message": f"Config '{config_key}' deactivated."}


@router.post("/reset/{group}", summary="Reset a group to defaults")
async def reset_group_defaults(
    group: str,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Reset all configs in a group to their default values."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")

    if group not in GROUP_METADATA:
        raise HTTPException(status_code=404, detail=f"Unknown group: {group}")

    user_id = current_user.get("user_ID")
    reset_count = 0

    for key, meta in CONFIG_METADATA.items():
        if meta.get("group") != group:
            continue
        if meta.get("managed_by"):
            continue
        if meta.get("is_secret"):
            continue

        default_value = meta.get("default", "")
        current_value = app_config.get(key, "")

        if current_value != default_value:
            app_config.set(key, default_value, description=meta.get("description"))
            reset_count += 1

    if app_config.db and reset_count > 0:
        try:
            app_config.db.audit(
                action="config.reset_group",
                entity_type="config_group",
                entity_id=group,
                user_id=user_id,
                details={"reset_count": reset_count},
            )
        except Exception:
            pass

    logger.info("Config group '%s': %d keys reset to defaults by user %s",
                group, reset_count, user_id)
    return {
        "message": f"Reset {reset_count} config(s) in '{group}' to defaults.",
        "reset_count": reset_count,
    }
