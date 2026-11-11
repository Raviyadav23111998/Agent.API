"""
Brain Repository — FTS search + document CRUD on ag_brain.documents.
════════════════════════════════════════════════════════════════════
"""
import hashlib
import logging
from typing import Optional, List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class BrainRepository:
    def __init__(self, db: TenantDB):
        self._db = db

    def search(self, query: str, owner_id: str = None, doc_type: str = None,
               limit: int = 10, app_id: int = None) -> List[Dict]:
        """Full-text search — scoped by owner_id and app_id."""
        params = [query, query]
        filters = ""
        if doc_type:
            filters += " AND doc_type = %s"
            params.append(doc_type)
        if owner_id:
            filters += " AND owner_id IN (%s, '__tenant__')"
            params.append(owner_id)
        if app_id:
            filters += " AND app_id = %s"
            params.append(app_id)
        params.append(limit)
        return self._db.fetch_all(f"""
            SELECT doc_id, title, source_path, doc_type,
                   ts_rank(fts_vector, plainto_tsquery('english', %s)) AS rank,
                   LEFT(content, 300) AS snippet
            FROM ag_brain.documents
            WHERE fts_vector @@ plainto_tsquery('english', %s)
                  AND status = 'indexed' {filters}
            ORDER BY rank DESC LIMIT %s
        """, tuple(params))

    def list_documents(self, owner_id: str = None, doc_type: str = None,
                       limit: int = 1000, app_id: int = None) -> List[Dict]:
        """List documents — scoped by owner_id and app_id."""
        params = []
        where = "WHERE 1=1"
        if owner_id:
            where += " AND owner_id IN (%s, '__tenant__')"
            params.append(owner_id)
        if doc_type:
            where += " AND doc_type = %s"
            params.append(doc_type)
        if app_id:
            where += " AND app_id = %s"
            params.append(app_id)
        params.append(limit)
        return self._db.fetch_all(f"""
            SELECT doc_id, source_path, doc_type, title, content_hash,
                   token_count, status, owner_id, app_id, created_at
            FROM ag_brain.documents {where}
            ORDER BY created_at DESC LIMIT %s
        """, tuple(params))

    def get_document(self, doc_id: int, owner_id: str = None) -> Optional[Dict]:
        """Get document — SECURITY: scoped to owner_id + __tenant__."""
        if owner_id:
            return self._db.fetch_one("""
                SELECT doc_id, source_path, doc_type, title, content,
                       content_hash, token_count, status, owner_id, created_at
                FROM ag_brain.documents
                WHERE doc_id = %s AND owner_id IN (%s, '__tenant__')
            """, (doc_id, owner_id))
        return self._db.fetch_one("""
            SELECT doc_id, source_path, doc_type, title, content,
                   content_hash, token_count, status, owner_id, created_at
            FROM ag_brain.documents WHERE doc_id = %s
        """, (doc_id,))

    def ingest_document(self, source_path: str, content: str,
                        title: str = '', doc_type: str = 'document',
                        owner_id: str = '__tenant__', created_by: int = None,
                        app_id: int = None) -> Dict:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        token_count = len(content.split())
        return self._db.execute_returning("""
            INSERT INTO ag_brain.documents
                (source_path, doc_type, title, content, content_hash,
                 token_count, status, owner_id, created_by, app_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'indexed', %s, %s, %s)
            ON CONFLICT (source_path) DO UPDATE SET
                content = EXCLUDED.content, content_hash = EXCLUDED.content_hash,
                token_count = EXCLUDED.token_count, title = EXCLUDED.title,
                status = 'indexed', app_id = EXCLUDED.app_id
            RETURNING doc_id, source_path, title, status, app_id
        """, (source_path, doc_type, title, content, content_hash,
              token_count, owner_id, created_by, app_id))

    def delete_document(self, doc_id: int, owner_id: str = None, app_id: int = None):
        """Delete document — only if owned by user or __tenant__, WITHIN app.

        app_id closes a gap this class's contract already claimed to enforce.
        Ingestion writes documents as owner_id='__tenant__' by design, so
        filtering on owner alone made every ingested document deletable by any
        signed-in user of any OTHER application in the tenant.

        None means unscoped and is reached only by an admin who asked for
        cross-app reach; every other caller arrives already scoped.
        """
        where = ["doc_id = %s"]
        params = [doc_id]

        if owner_id:
            where.append("owner_id IN (%s, '__tenant__')")
            params.append(owner_id)
        if app_id is not None:
            where.append("app_id = %s")
            params.append(app_id)

        self._db.execute(
            f"DELETE FROM ag_brain.documents WHERE {' AND '.join(where)}",
            tuple(params),
        )

    def get_stats(self, owner_id: str = None, app_id: int = None) -> Dict:
        """Knowledge base stats — scoped by owner_id and app_id."""
        params = []
        where = "WHERE 1=1"
        if owner_id:
            where += " AND owner_id IN (%s, '__tenant__')"
            params.append(owner_id)
        if app_id:
            where += " AND app_id = %s"
            params.append(app_id)
        row = self._db.fetch_one(f"""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'indexed') as indexed,
                   COALESCE(SUM(token_count), 0) as total_tokens
            FROM ag_brain.documents {where}
        """, tuple(params) if params else None)
        return row or {"total": 0, "indexed": 0, "total_tokens": 0}
