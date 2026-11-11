"""
Cron Service — Business logic for Cron Admin CRUD.
"""
from typing import List, Optional
from api.schemas.cron import CronJobCreateRequest, CronJobUpdateRequest, CronJobDTO
from api.repositories.cron_repo import CronRepository

class CronAdminService:
    def __init__(self, repo: CronRepository):
        self._repo = repo

    async def list_jobs(self) -> List[CronJobDTO]:
        raw_jobs = self._repo.list_jobs(include_disabled=True)
        return [CronJobDTO(**j) for j in raw_jobs]

    async def get_job(self, job_id: str) -> Optional[CronJobDTO]:
        job = self._repo.get_job(job_id)
        if not job:
            return None
        return CronJobDTO(**job)

    async def create_job(self, req: CronJobCreateRequest) -> CronJobDTO:
        job = self._repo.create_job(
            prompt=req.prompt,
            schedule=req.schedule,
            name=req.name,
            repeat=req.repeat_times,
            deliver=req.deliver,
            app_id=req.app_id,
            persona_id=req.persona_id
        )
        return CronJobDTO(**job)

    async def update_job(self, job_id: str, req: CronJobUpdateRequest) -> Optional[CronJobDTO]:
        update_data = req.model_dump(exclude_unset=True)
        if "repeat_times" in update_data:
            update_data["repeat"] = update_data.pop("repeat_times")
            
        job = self._repo.update_job(job_id=job_id, **update_data)
        if not job:
            return None
        return CronJobDTO(**job)

    async def delete_job(self, job_id: str) -> bool:
        return self._repo.delete_job(job_id)

