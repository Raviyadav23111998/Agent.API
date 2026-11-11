"""
Cron Repository — Bridges API layer with agent.core.cron.jobs
═════════════════════════════════════════════════════════════
"""
import logging
from typing import List, Dict, Any, Optional

from core.tenant_db import TenantDB
from cron import jobs

logger = logging.getLogger(__name__)

class CronRepository:
    """Repository for managing Cron Jobs."""
    
    def __init__(self, db: TenantDB):
        self._db = db
        jobs.init_db(db)

    def list_jobs(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        return jobs.list_jobs(include_disabled=include_disabled)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return jobs.get_job(job_id)

    def create_job(self, prompt: str, schedule: str, name: Optional[str] = None,
                   repeat: Optional[int] = None, deliver: Optional[str] = None,
                   app_id: Optional[int] = None,
                   persona_id: Optional[int] = None) -> Dict[str, Any]:
        return jobs.create_job(
            prompt=prompt,
            schedule=schedule,
            name=name,
            repeat=repeat,
            deliver=deliver,
            app_id=app_id,
            persona_id=persona_id
        )

    def update_job(self, job_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        return jobs.update_job(job_id=job_id, **kwargs)

    def delete_job(self, job_id: str) -> bool:
        return jobs.remove_job(job_id)
