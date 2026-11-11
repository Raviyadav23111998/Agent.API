import logging
import os
import uuid
import shutil
from typing import Dict, List, Optional
from fastapi import UploadFile

from api.repositories.system_repo import SystemRepository
from core.config import app_config

logger = logging.getLogger(__name__)


class SystemService:
    def __init__(self, repo: SystemRepository):
        self._repo = repo

    async def add_update_file(
        self,
        file: UploadFile,
        file_type: str,
        associated_to: str,
        associated_id: int,
        tenant_id: str = "default",
        current_user_id: int = 0,
        title: Optional[str] = None,
        description: Optional[str] = None,
        sequence: Optional[int] = None
    ) -> Dict:
        """
        Uploads file locally mimicking SMSystems:
        TenantPath + // + ImageMiddlePath + guid + extension
        """
        base_path = app_config.get("agent.data_dir", ".ag_data")
        if file_type == "IMG":
            base_path = os.path.join(base_path, "Images")
        elif file_type == "DOC":
            base_path = os.path.join(base_path, "Docs")
        else:
            base_path = os.path.join(base_path, "Files")

        tenant_path = os.path.join(base_path, tenant_id)
        image_middle_path = os.path.join(associated_to, str(associated_id))
        full_dir = os.path.join(tenant_path, image_middle_path)

        os.makedirs(full_dir, exist_ok=True)

        guid = str(uuid.uuid4())
        _, ext = os.path.splitext(file.filename)
        if not ext:
            ext = ".bin"

        file_name = f"{guid}{ext}"
        full_file_path = os.path.join(full_dir, file_name)

        with open(full_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        db_file_path = f"{associated_to}/{associated_id}/{file_name}"

        file_id = self._repo.add_update_file(
            file_type=file_type,
            associated_to=associated_to,
            associated_id=associated_id,
            file_path=db_file_path,
            file_name=file.filename,
            extension=ext,
            title=title,
            description=description,
            sequence=sequence,
            current_user_id=current_user_id
        )

        return {"file_id": file_id, "file_path": db_file_path}

    def get_files_by_type_and_id(self, file_type: str, associated_to: str, associated_id: int) -> List[Dict]:
        return self._repo.get_files_by_type_and_id(file_type, associated_to, associated_id)

    def delete_file(self, file_id: int, tenant_id: str = "default") -> bool:
        file_record = self._repo.get_file_by_id(file_id)
        if not file_record:
            return False

        full_file_path = self.get_physical_file_path(file_record, tenant_id)
        if full_file_path and os.path.exists(full_file_path):
            os.remove(full_file_path)

        return self._repo.delete_file_by_id(file_id)

    def get_physical_file_path(self, file_record: Dict, tenant_id: str = "default") -> Optional[str]:
        if not file_record:
            return None
        base_path = app_config.get("agent.data_dir", ".ag_data")
        if file_record["file_type"] == "IMG":
            base_path = os.path.join(base_path, "Images")
        elif file_record["file_type"] == "DOC":
            base_path = os.path.join(base_path, "Docs")
        else:
            base_path = os.path.join(base_path, "Files")
            
        return os.path.join(base_path, tenant_id, file_record["file_path"])

    def get_code_types(self) -> List[Dict]:
        return self._repo.get_code_types()
        
    def get_all_codes(self) -> List[Dict]:
        return self._repo.get_all_codes()

    def get_codes_by_type(self, code_type_id: int) -> List[Dict]:
        return self._repo.get_codes_by_type(code_type_id)

    def add_update_code(self, code_data: Dict, current_user_id: int) -> int:
        return self._repo.add_update_code(code_data, current_user_id)

    def delete_code(self, code_id: int) -> bool:
        return self._repo.delete_code(code_id)

    def get_addresses(self, associated_to: str, associated_id: int) -> List[Dict]:
        return self._repo.get_addresses(associated_to, associated_id)

    def add_update_address(self, addr: Dict, current_user_id: int) -> int:
        return self._repo.add_update_address(addr, current_user_id)

    def delete_address(self, address_id: int) -> bool:
        return self._repo.delete_address(address_id)
