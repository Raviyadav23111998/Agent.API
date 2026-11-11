import logging
from typing import Optional, Dict, List
from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class SystemRepository:
    def __init__(self, db: TenantDB):
        self._db = db

    def add_update_file(
        self,
        file_type: str,
        associated_to: str,
        associated_id: int,
        file_path: str,
        file_name: str,
        extension: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        sequence: Optional[int] = None,
        file_id: Optional[int] = None,
        current_user_id: int = 0,
    ) -> int:
        if file_id:
            self._db.execute("""
                UPDATE ag_system.files SET
                    file_type = %s, associated_to = %s, associated_id = %s,
                    file_path = %s, file_name = %s, extension = %s
                WHERE file_id = %s
            """, (file_type, associated_to, associated_id, file_path, file_name,
                  extension, file_id))
            return file_id
        else:
            row = self._db.execute_returning("""
                INSERT INTO ag_system.files (
                    file_type, associated_to, associated_id, file_path,
                    file_name, extension, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING file_id
            """, (file_type, associated_to, associated_id, file_path, file_name,
                  extension, current_user_id))
            return row['file_id']

    def get_file_by_id(self, file_id: int) -> Optional[Dict]:
        return self._db.fetch_one("""
            SELECT * FROM ag_system.files WHERE file_id = %s
        """, (file_id,))

    def get_files_by_type_and_id(self, file_type: str, associated_to: str, associated_id: int) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT * FROM ag_system.files
            WHERE file_type = %s AND associated_to = %s AND associated_id = %s
            ORDER BY file_id DESC
        """, (file_type, associated_to, associated_id))

    def delete_file_by_id(self, file_id: int) -> bool:
        self._db.execute("DELETE FROM ag_system.files WHERE file_id = %s", (file_id,))
        return True

    def get_code_types(self) -> List[Dict]:
        return self._db.fetch_all("SELECT * FROM ag_system.code_types ORDER BY name")

    def get_codes_by_type(self, code_type_id: int) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT * FROM ag_system.codes
            WHERE code_type_id = %s
            ORDER BY weightage ASC, english_name ASC
        """, (code_type_id,))
        
    def get_all_codes(self) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT c.*, ct.name as code_type_name 
            FROM ag_system.codes c
            JOIN ag_system.code_types ct ON c.code_type_id = ct.code_type_id
            ORDER BY ct.name ASC, c.weightage ASC, c.english_name ASC
        """)

    def add_update_code(self, code_data: Dict, current_user_id: int) -> int:
        code_id = code_data.get('code_id')
        if code_id:
            self._db.execute("""
                UPDATE ag_system.codes SET
                    code_type_id = %s, parent_id = %s, code = %s, weightage = %s,
                    value = %s, english_name = %s, hindi_name = %s,
                    updated_by = %s, updation_date = ag_common.utc_now()
                WHERE code_id = %s
            """, (code_data['code_type_id'], code_data.get('parent_id'), code_data['code'],
                  code_data.get('weightage'), code_data.get('value'), code_data.get('english_name'),
                  code_data.get('hindi_name'), current_user_id, code_id))
            return code_id
        else:
            row = self._db.execute_returning("""
                INSERT INTO ag_system.codes (
                    code_type_id, parent_id, code, weightage, value,
                    english_name, hindi_name, created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING code_id
            """, (code_data['code_type_id'], code_data.get('parent_id'), code_data['code'],
                  code_data.get('weightage'), code_data.get('value'), code_data.get('english_name'),
                  code_data.get('hindi_name'), current_user_id))
            return row['code_id']

    def delete_code(self, code_id: int) -> bool:
        self._db.execute("DELETE FROM ag_system.codes WHERE code_id = %s", (code_id,))
        return True

    def add_update_address(self, addr: Dict, current_user_id: int) -> int:
        address_id = addr.get('address_id')
        if address_id:
            self._db.execute("""
                UPDATE ag_system.address SET
                    address_type = %s, associated_to = %s, associated_id = %s,
                    address_line1 = %s, address_line2 = %s, suburb = %s,
                    postcode = %s, state_id = %s, country_id = %s, geo_location = %s,
                    updated_by = %s, updation_date = ag_common.utc_now()
                WHERE address_id = %s
            """, (addr['address_type'], addr['associated_to'], addr['associated_id'],
                  addr['address_line1'], addr.get('address_line2'), addr.get('suburb'),
                  addr.get('postcode'), addr.get('state_id'), addr.get('country_id'),
                  addr.get('geo_location'), current_user_id, address_id))
            return address_id
        else:
            row = self._db.execute_returning("""
                INSERT INTO ag_system.address (
                    address_type, associated_to, associated_id, address_line1,
                    address_line2, suburb, postcode, state_id, country_id, geo_location,
                    created_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING address_id
            """, (addr['address_type'], addr['associated_to'], addr['associated_id'],
                  addr['address_line1'], addr.get('address_line2'), addr.get('suburb'),
                  addr.get('postcode'), addr.get('state_id'), addr.get('country_id'),
                  addr.get('geo_location'), current_user_id))
            return row['address_id']

    def get_addresses(self, associated_to: str, associated_id: int) -> List[Dict]:
        return self._db.fetch_all("""
            SELECT * FROM ag_system.address
            WHERE associated_to = %s AND associated_id = %s
            ORDER BY address_id ASC
        """, (associated_to, associated_id))

    def delete_address(self, address_id: int) -> bool:
        self._db.execute("DELETE FROM ag_system.address WHERE address_id = %s", (address_id,))
        return True
