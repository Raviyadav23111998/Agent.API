"""
Memory Repository — CRUD + FTS search on ag_memory.memories.
═════════════════════════════════════════════════════════════
"""
import logging
from typing import Optional, List, Dict

from core.tenant_db import TenantDB

logger = logging.getLogger(__name__)


class MemoryRepository:
    def __init__(self, db: TenantDB):
        self._db = db

    def store(self, user_id: str, key: str, value: str,
              category: str = 'fact', layer: str = 'semantic',
              source: str = 'api') -> Dict:
        return self._db.execute_returning("""
            INSERT INTO ag_memory.memories (user_id, key, value, category, layer, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, key) DO UPDATE SET
                value = EXCLUDED.value, category = EXCLUDED.category,
                source = EXCLUDED.source, access_count = ag_memory.memories.access_count + 1
            RETURNING memory_id, user_id, key, value, category, layer, created_at
        """, (user_id, key, value, category, layer, source))

    def recall(self, query: str, user_id: str = None,
               category: str = None, limit: int = 10) -> List[Dict]:
        """FTS recall — fix: query must appear exactly twice (rank + WHERE)."""
        params = [query, query]
        extra_filters = ""
        if user_id:
            extra_filters += " AND (user_id = %s OR user_id = '__tenant__')"
            params.append(user_id)
        if category:
            extra_filters += " AND category = %s"
            params.append(category)
        params.append(limit)
        return self._db.fetch_all(f"""
            SELECT memory_id, user_id, layer, category, key, value,
                   confidence, source, access_count, created_at, updated_at,
                   ts_rank(fts_vector, plainto_tsquery('english', %s)) AS rank
            FROM ag_memory.memories
            WHERE fts_vector @@ plainto_tsquery('english', %s)
                  {extra_filters}
            ORDER BY rank DESC LIMIT %s
        """, tuple(params))

    def list_memories(self, user_id: str, category: str = None,
                      limit: int = 50) -> List[Dict]:
        params = [user_id]
        cat_filter = ""
        if category:
            cat_filter = "AND category = %s"
            params.append(category)
        params.append(limit)
        return self._db.fetch_all(f"""
            SELECT memory_id, user_id, layer, category, key, value,
                   confidence, source, access_count, created_at, updated_at
            FROM ag_memory.memories
            WHERE (user_id = %s OR user_id = '__tenant__') {cat_filter}
            ORDER BY updated_at DESC LIMIT %s
        """, tuple(params))

    def get_memory(self, memory_id: int) -> Optional[Dict]:
        return self._db.fetch_one("""
            SELECT memory_id, user_id, layer, category, key, value,
                   confidence, source, access_count, created_at, updated_at
            FROM ag_memory.memories WHERE memory_id = %s
        """, (memory_id,))

    def delete_memory(self, memory_id: int, user_id: str = None):
        """Delete memory — scoped by user_id for ownership."""
        if user_id:
            self._db.execute("""
                DELETE FROM ag_memory.memories
                WHERE memory_id = %s AND (user_id = %s OR user_id = '__tenant__')
            """, (memory_id, user_id))
        else:
            self._db.execute("DELETE FROM ag_memory.memories WHERE memory_id = %s", (memory_id,))

    def get_stats(self, user_id: str = None) -> Dict:
        if user_id:
            row = self._db.fetch_one("""
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE layer = 'semantic') as semantic,
                       COUNT(*) FILTER (WHERE layer = 'episodic') as episodic,
                       COUNT(*) FILTER (WHERE layer = 'session') as session_count,
                       COUNT(*) FILTER (WHERE layer = 'company') as company
                FROM ag_memory.memories
                WHERE user_id = %s OR user_id = '__tenant__'
            """, (user_id,))
        else:
            row = self._db.fetch_one("""
                SELECT COUNT(*) as total,
                       COUNT(DISTINCT user_id) as unique_users
                FROM ag_memory.memories
            """)
        return row or {}
