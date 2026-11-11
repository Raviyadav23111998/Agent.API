"""
Cron Admin Router — REST endpoints for managing cron jobs.
"""
import logging
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import require_admin
from api.schemas.cron import CronJobCreateRequest, CronJobUpdateRequest, CronJobDTO
from api.services.cron_service import CronAdminService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/admin/crons", tags=["Cron Admin"])

def _get_cron_service(request: Request) -> CronAdminService:
    if not hasattr(request.app.state, "cron_admin_service"):
        request.app.state.cron_admin_service = CronAdminService()
    return request.app.state.cron_admin_service

@router.get("", response_model=List[CronJobDTO], summary="List all cron jobs")
async def list_jobs(request: Request, current_user: Dict = Depends(require_admin)):
    svc = _get_cron_service(request)
    return await svc.list_jobs()

@router.post("", response_model=CronJobDTO, summary="Create a cron job")
async def create_job(req: CronJobCreateRequest, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_cron_service(request)
    try:
        return await svc.create_job(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{job_id}", response_model=CronJobDTO, summary="Get cron job details")
async def get_job(job_id: str, request: Request,
                  current_user: Dict = Depends(require_admin)):
    svc = _get_cron_service(request)
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return job

@router.put("/{job_id}", response_model=CronJobDTO, summary="Update cron job")
async def update_job(job_id: str, req: CronJobUpdateRequest, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_cron_service(request)
    try:
        job = await svc.update_job(job_id, req)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        return job
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{job_id}", summary="Delete a cron job")
async def delete_job(job_id: str, request: Request,
                     current_user: Dict = Depends(require_admin)):
    svc = _get_cron_service(request)
    deleted = await svc.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return {"message": "Cron job deleted"}
