import logging
import os
from typing import Dict, Optional
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from api.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/system", tags=["System"])

# Upload guards (S3): bound size and restrict to safe content types so an
# upload can't fill the disk or plant an executable/active-content file.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_UPLOAD_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif",
    "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
    "application/pdf", "text/plain", "text/csv", "application/json",
    "application/zip",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


async def _validate_upload(file: UploadFile) -> None:
    """Reject oversized or disallowed uploads before they are stored."""
    ctype = (file.content_type or "").lower().split(";")[0].strip()
    if ctype and ctype not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{ctype}'. Allowed: images, PDF, "
                   f"Office documents, CSV, text, JSON, ZIP.")
    # Bounded read: pull at most MAX+1 bytes to detect oversize without
    # loading an arbitrarily large file fully into memory, then rewind so the
    # service can store it.
    head = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(head) > MAX_UPLOAD_BYTES:
        await file.seek(0)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    await file.seek(0)


def _get_system_service(request: Request):
    return request.app.state.system_service


class CodeRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    code_id: Optional[int] = None
    code_type_id: int
    parent_id: Optional[int] = None
    code: str
    weightage: Optional[int] = None
    value: Optional[str] = None
    english_name: Optional[str] = None
    hindi_name: Optional[str] = None


class AddressRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    address_id: Optional[int] = None
    address_type: str
    associated_to: str
    associated_id: int
    address_line1: str
    address_line2: Optional[str] = None
    suburb: Optional[str] = None
    postcode: Optional[str] = None
    state_id: Optional[int] = None
    country_id: Optional[int] = None
    geo_location: Optional[str] = None


@router.post("/files")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    file_type: str = Form(...),
    associated_to: str = Form(...),
    associated_id: int = Form(...),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    sequence: Optional[int] = Form(None),
    current_user: Dict = Depends(get_current_user),
):
    await _validate_upload(file)
    svc = _get_system_service(request)
    current_uid = int(current_user.get("user_ID", 0))
    tenant_id = current_user.get("tenant_id", "default")

    result = await svc.add_update_file(
        file=file,
        file_type=file_type,
        associated_to=associated_to,
        associated_id=associated_id,
        tenant_id=tenant_id,
        current_user_id=current_uid,
        title=title,
        description=description,
        sequence=sequence
    )
    return result

@router.get("/files/{file_type}/{associated_to}/{associated_id}")
async def get_files(
    file_type: str,
    associated_to: str,
    associated_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    return svc.get_files_by_type_and_id(file_type, associated_to, associated_id)

@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    tenant_id = current_user.get("tenant_id", "default")
    success = svc.delete_file(file_id, tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    return {"message": "File deleted"}

@router.get("/files/download/{file_id}")
async def download_file(
    file_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    """Download a file the caller is entitled to.

    SECURITY: authentication is required and the tenant is taken from the
    caller's token — never a client query param. The physical path is
    resolved under the authenticated tenant's directory (mirroring
    delete_file), so a file belonging to another tenant simply does not
    exist for this caller and 404s. This closes the prior unauthenticated,
    cross-tenant IDOR where file_id (a sequential int) + a client-supplied
    tenant_id let anyone enumerate and download any tenant's files.
    """
    svc = _get_system_service(request)
    tenant_id = current_user.get("tenant_id", "default")

    file_record = svc._repo.get_file_by_id(file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    physical_path = svc.get_physical_file_path(file_record, tenant_id)
    if not physical_path or not os.path.exists(physical_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(physical_path)


@router.get("/code-types")
async def get_code_types(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    return svc.get_code_types()

@router.get("/codes")
async def get_all_codes(
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    return svc.get_all_codes()

@router.get("/codes/type/{code_type_id}")
async def get_codes_by_type(
    code_type_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    return svc.get_codes_by_type(code_type_id)

@router.post("/codes")
@router.put("/codes/{code_id}")
async def add_update_code(
    code_req: CodeRequest,
    request: Request,
    code_id: Optional[int] = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    current_uid = int(current_user.get("user_ID", 0))
    if code_id:
        code_req.code_id = code_id
    result_id = svc.add_update_code(code_req.dict(), current_uid)
    return {"code_id": result_id}

@router.delete("/codes/{code_id}")
async def delete_code(
    code_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    svc.delete_code(code_id)
    return {"message": "Code deleted"}


@router.get("/address/{associated_to}/{associated_id}")
async def get_addresses(
    associated_to: str,
    associated_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    return svc.get_addresses(associated_to, associated_id)

@router.post("/address")
@router.put("/address/{address_id}")
async def add_update_address(
    addr_req: AddressRequest,
    request: Request,
    address_id: Optional[int] = None,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    current_uid = int(current_user.get("user_ID", 0))
    if address_id:
        addr_req.address_id = address_id
    result_id = svc.add_update_address(addr_req.dict(), current_uid)
    return {"address_id": result_id}

@router.delete("/address/{address_id}")
async def delete_address(
    address_id: int,
    request: Request,
    current_user: Dict = Depends(get_current_user),
):
    svc = _get_system_service(request)
    svc.delete_address(address_id)
    return {"message": "Address deleted"}
