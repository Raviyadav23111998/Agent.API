import logging
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import get_current_user
from api.schemas.llm_config import LLMConfigResponse, LLMConfigUpdateRequest
from core.config import app_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LLM Config"])

def _is_admin(current_user: dict) -> bool:
    role = current_user.get("role", "member").lower()
    return role in ["admin", "superadmin", "administrator", "owner", "tenant owner"]

def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 5:
        return "*" * len(secret)
    return "*" * (len(secret) - 5) + secret[-5:]

@router.get("/v1/admin/llm-config", response_model=LLMConfigResponse)
async def get_llm_config(
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Get the global LLM configuration (Admin Only)."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return LLMConfigResponse(
        provider=app_config.get("llm.provider", ""),
        model=app_config.get("llm.model", ""),
        base_url=app_config.get("llm.base_url", ""),
        api_key=mask_secret(app_config.get("llm.api_key", "")),
        provider_order=app_config.get("llm.provider_order", ""),
        max_tokens=app_config.get("llm.max_tokens", "16000"),
        temperature=app_config.get("llm.temperature", "0.7")
    )

@router.put("/v1/admin/llm-config")
async def update_llm_config(
    body: LLMConfigUpdateRequest,
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Update the global LLM configuration and live-reload the cache (Admin Only)."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    updates = 0
    
    if body.provider is not None:
        app_config.set("llm.provider", body.provider, is_secret=False)
        updates += 1
    if body.model is not None:
        app_config.set("llm.model", body.model, is_secret=False)
        updates += 1
    if body.base_url is not None:
        app_config.set("llm.base_url", body.base_url, is_secret=False)
        updates += 1
    if body.api_key is not None and not body.api_key.startswith("*"):
        app_config.set("llm.api_key", body.api_key, is_secret=True)
        updates += 1
    if body.provider_order is not None:
        app_config.set("llm.provider_order", body.provider_order, is_secret=False)
        updates += 1
    if body.max_tokens is not None:
        app_config.set("llm.max_tokens", body.max_tokens, is_secret=False)
        updates += 1
    if body.temperature is not None:
        app_config.set("llm.temperature", body.temperature, is_secret=False)
        updates += 1
        
    logger.info(f"LLM Configuration updated by admin user {current_user.get('user_ID')}. Live-reloaded {updates} keys.")
    return {"message": f"Successfully updated {updates} LLM settings and hot-reloaded the system cache."}

@router.post("/v1/admin/llm-config/sync")
async def sync_llm_models(
    request: Request,
    current_user: Dict = Depends(get_current_user)
):
    """Fetch models from OpenRouter and populate ag_system.codes (Admin Only)."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        import urllib.request
        import json
        req = urllib.request.Request('https://openrouter.ai/api/v1/models')
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            models = data.get('data', [])
    except Exception as e:
        logger.error(f"Failed to fetch models: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch models from OpenRouter")
        
    db = request.app.state.db
    
    existing_types = db.fetch_all("SELECT * FROM ag_system.code_types WHERE name IN ('LLM_PROVIDER', 'LLM_MODEL', 'LLM_BASE_URL')")
    type_map = {t['name']: t['code_type_id'] for t in existing_types}
    
    for t_name, t_desc in [('LLM_PROVIDER', 'Providers'), ('LLM_MODEL', 'Models'), ('LLM_BASE_URL', 'URLs')]:
        if t_name not in type_map:
            row = db.execute_returning("INSERT INTO ag_system.code_types (name, description, created_by) VALUES (%s, %s, %s) RETURNING code_type_id", (t_name, t_desc, 0))
            type_map[t_name] = row['code_type_id']
            
    p_tid = type_map['LLM_PROVIDER']
    m_tid = type_map['LLM_MODEL']
    u_tid = type_map['LLM_BASE_URL']
    
    db.execute("DELETE FROM ag_system.codes WHERE code_type_id IN (%s, %s, %s)", (p_tid, m_tid, u_tid))
    
    urls = {
        'openai': 'https://api.openai.com/v1/chat/completions',
        'anthropic': 'https://api.anthropic.com/v1/messages',
        'google': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
        'deepseek': 'https://api.deepseek.com/v1/chat/completions',
        'mistralai': 'https://api.mistral.ai/v1/chat/completions',
        'groq': 'https://api.groq.com/openai/v1/chat/completions',
        'cohere': 'https://api.cohere.ai/v1/chat/completions',
        'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
        'meta-llama': 'https://api.llama.api/v1/chat/completions'
    }
    
    allowed_providers = ['openai', 'anthropic', 'google', 'meta-llama', 'mistralai', 'cohere', 'qwen', 'deepseek', 'nvidia', 'amazon', 'minimax']
    provider_id_map = {}
    
    for i, m in enumerate(models):
        parts = m['id'].split('/')
        if len(parts) < 2:
            continue
            
        prov_slug = parts[0]
        if prov_slug not in allowed_providers:
            continue
            
        model_slug = '/'.join(parts[1:])
        
        if prov_slug not in provider_id_map:
            name_parts = m['name'].split(':')
            prov_name = name_parts[0].strip() if len(name_parts) >= 2 else prov_slug.capitalize()
            
            row = db.execute_returning(
                "INSERT INTO ag_system.codes (code_type_id, code, english_name, created_by) VALUES (%s, %s, %s, %s) RETURNING code_id",
                (p_tid, prov_slug, prov_name, 0)
            )
            pid = row['code_id']
            provider_id_map[prov_slug] = pid
            
            url = urls.get(prov_slug, f'https://api.{prov_slug}.com/v1/chat/completions')
            db.execute("INSERT INTO ag_system.codes (code_type_id, parent_id, code, value, english_name, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
                (u_tid, pid, f"{prov_slug}_url", url, f"{prov_name} URL", 0))
                
        pid = provider_id_map[prov_slug]
        model_name = m['name']
        if ':' in model_name:
            model_name = model_name.split(':', 1)[1].strip()
            
        db.execute(
            "INSERT INTO ag_system.codes (code_type_id, parent_id, code, weightage, english_name, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
            (m_tid, pid, model_slug, i, model_name, 0)
        )

    row = db.execute_returning("INSERT INTO ag_system.codes (code_type_id, code, english_name, created_by) VALUES (%s, %s, %s, %s) RETURNING code_id", (p_tid, 'openrouter', 'OpenRouter', 0))
    or_pid = row['code_id']
    db.execute("INSERT INTO ag_system.codes (code_type_id, parent_id, code, value, english_name, created_by) VALUES (%s, %s, %s, %s, %s, %s)", (u_tid, or_pid, "openrouter_url", "https://openrouter.ai/api/v1/chat/completions", "OpenRouter URL", 0))
    for i, m in enumerate(models):
        if m['id'].split('/')[0] not in allowed_providers: continue
        db.execute("INSERT INTO ag_system.codes (code_type_id, parent_id, code, weightage, english_name, created_by) VALUES (%s, %s, %s, %s, %s, %s)", (m_tid, or_pid, m['id'], i, m['name'], 0))
            
    return {"message": "Successfully synced native structure from OpenRouter!"}
