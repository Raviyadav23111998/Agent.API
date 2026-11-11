"""
Agent — Tenant DB End-to-End Flow Test
=====================================================
Tests every data flow through agent_uat PostgreSQL:

  Flow  1: Auth — User provisioning + login
  Flow  2: Auth — RBAC permission checks
  Flow  3: Auth — Permission overrides
  Flow  4: Auth — API key management
  Flow  5: Auth — Session tracking
  Flow  6: Brain — Document ingestion + FTS search
  Flow  7: Brain — Content cache + TTL expiry
  Flow  8: Brain — Answer cache + hit tracking
  Flow  9: Brain — Entity graph + FTS
  Flow 10: Brain — Sync state tracking
  Flow 11: Memory — Store + recall + FTS
  Flow 12: Memory — Tags + filtered recall
  Flow 13: Memory — Entity graph (conversation)
  Flow 14: Memory — Expiry cleanup
  Flow 15: Agents — Definition CRUD
  Flow 16: Agents — Run logging
  Flow 17: Agents — Cron job management
  Flow 18: System — Config get/set
  Flow 19: System — Integration CRUD
  Flow 20: System — Audit trail
  Flow 21: System — Conversation summaries
  Flow 22: System — Tenant stats dashboard
  Flow 23: System — Migration history
  Flow 24: Cross-cutting — Scope isolation (user A can't see user B)
  Flow 25: Cross-cutting — updated_at triggers

Run:
    python3 migrations/test_e2e_flows.py
"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tenant_db import TenantDB

DB_URL = os.environ.get(
    "AG_DATABASE_URL",
    "postgresql://agent_uat_user:ag3nt_uat_s3cure_2024@localhost:15432/agent_uat"
)

passed = 0
failed = 0
errors = []


def test(name, func):
    global passed, failed
    try:
        func()
        passed += 1
        print(f"  ✅ {name}")
    except Exception as e:
        failed += 1
        errors.append((name, str(e)))
        print(f"  ❌ {name}: {e}")


def main():
    global passed, failed

    db = TenantDB(DB_URL)
    db.connect()
    print(f"\n{'═' * 65}")
    print(f"  TENANT DB E2E FLOW TEST — {repr(db)}")
    print(f"{'═' * 65}\n")

    print("── Setup ──")
    alice = db.upsert_user("test_alice", "Alice Admin", "alice@test.com", "web", "admin")
    bob = db.upsert_user("test_bob", "Bob Member", "bob@test.com", "telegram", "member")
    eve = db.upsert_user("test_eve", "Eve Viewer", "eve@test.com", "api", "viewer")
    print(f"  Created: Alice(id={alice['user_id']}), Bob(id={bob['user_id']}), Eve(id={eve['user_id']})")
    print()

    print("── 1. Auth Flows ──")

    def flow_1():
        """User provisioning + login"""
        user = db.upsert_user("test_new", "New User", platform="cli")
        assert user['full_name'] == "New User"
        user2 = db.upsert_user("test_new", "New User Updated", platform="web")
        assert user2['user_id'] == user['user_id']
        alice_by_email = db.get_user_by_email("alice@test.com")
        assert alice_by_email['full_name'] == "Alice Admin"
        db.execute("DELETE FROM ag_auth.users WHERE external_id = 'test_new'")

    def flow_2():
        """RBAC permission checks"""
        assert db.check_permission(alice['user_id'], 'brain_ingest', 'create') == True
        assert db.check_permission(alice['user_id'], 'system_settings', 'read') == True
        assert db.check_permission(alice['user_id'], 'system_settings', 'create') == False
        assert db.check_permission(bob['user_id'], 'ai_chat', 'create') == True
        assert db.check_permission(bob['user_id'], 'user_mgmt', 'create') == False
        assert db.check_permission(eve['user_id'], 'brain_search', 'read') == True
        assert db.check_permission(eve['user_id'], 'brain_search', 'create') == False

    def flow_3():
        """Permission overrides"""
        module_id = db.fetch_scalar(
            "SELECT module_id FROM ag_system.modules WHERE module_key = 'brain_ingest'")
        db.execute("""
            INSERT INTO ag_auth.user_permission_overrides 
                (user_id, module_id, can_create, can_read, reason, granted_by)
            VALUES (%s, %s, TRUE, TRUE, 'Special project access', %s)
        """, (eve['user_id'], module_id, alice['user_id']))
        assert db.check_permission(eve['user_id'], 'brain_ingest', 'create') == True
        db.execute("DELETE FROM ag_auth.user_permission_overrides WHERE user_id = %s",
                   (eve['user_id'],))

    def flow_4():
        """API key management"""
        import hashlib
        key_raw = "ag_test_key_1234567890"
        key_hash = hashlib.sha256(key_raw.encode()).hexdigest()
        db.execute("""
            INSERT INTO ag_auth.api_keys (user_id, key_prefix, key_hash, name, scopes)
            VALUES (%s, %s, %s, %s, %s::jsonb)
        """, (alice['user_id'], key_raw[:8], key_hash, 'Test Key',
              json.dumps(["ai_chat", "brain_search"])))
        key = db.fetch_one(
            "SELECT * FROM ag_auth.api_keys WHERE key_hash = %s AND is_active = TRUE",
            (key_hash,))
        assert key['name'] == 'Test Key'
        assert key['scopes'] == ["ai_chat", "brain_search"]
        db.execute("DELETE FROM ag_auth.api_keys WHERE key_hash = %s", (key_hash,))

    def flow_5():
        """Session tracking"""
        db.execute("""
            INSERT INTO ag_auth.user_sessions (session_id, user_id, platform, ip_address)
            VALUES (%s, %s, %s, %s)
        """, ("sess_alice_001", alice['user_id'], "web", "192.168.1.1"))
        session = db.fetch_one(
            "SELECT * FROM ag_auth.user_sessions WHERE session_id = %s",
            ("sess_alice_001",))
        assert session['platform'] == 'web'
        db.execute("""
            UPDATE ag_auth.user_sessions SET last_active_at = NOW() 
            WHERE session_id = %s
        """, ("sess_alice_001",))
        db.execute("DELETE FROM ag_auth.user_sessions WHERE session_id = 'sess_alice_001'")

    test("Flow  1: User provisioning + login", flow_1)
    test("Flow  2: RBAC permission checks", flow_2)
    test("Flow  3: Permission overrides", flow_3)
    test("Flow  4: API key management", flow_4)
    test("Flow  5: Session tracking", flow_5)
    print()

    print("── 2. Brain Flows ──")

    def flow_6():
        """Document ingestion + FTS search"""
        db.execute("DELETE FROM ag_brain.ingestion_log")
        db.execute("DELETE FROM ag_brain.documents WHERE source_path LIKE 'jira://%' OR source_path LIKE 'outlook://%' OR source_path LIKE 'slack://%'")
        
        for i, (src, title, content, owner) in enumerate([
            ("jira://PROJ-101", "API Redesign", 
             "We need to redesign the REST API to support GraphQL alongside existing endpoints",
             "__tenant__"),
            ("outlook://msg_abc", "Meeting Notes",
             "Discussed migration to PostgreSQL for the agent database. Alice will lead the effort.",
             f"user_{alice['user_id']}"),
            ("slack://C123/msg_456", "Deployment Update",
             "Deployed version 2.3.1 to production. All health checks passing.",
             "__tenant__"),
        ]):
            db.execute("""
                INSERT INTO ag_brain.documents 
                    (source_path, doc_type, title, content, content_hash, 
                     status, owner_id, created_by)
                VALUES (%s, 'document', %s, %s, %s, 'indexed', %s, %s)
            """, (src, title, content, f"hash_{i}", owner, alice['user_id']))
        
        results = db.fetch_all("""
            SELECT doc_id, title, ts_rank(fts_vector, q) as rank
            FROM ag_brain.documents, to_tsquery('english', 'PostgreSQL & migration') q
            WHERE fts_vector @@ q
            ORDER BY rank DESC
        """)
        assert len(results) >= 1
        assert "Meeting" in results[0]['title']
        
        tenant_docs = db.fetch_all("""
            SELECT doc_id, title FROM ag_brain.documents 
            WHERE owner_id = '__tenant__' AND fts_vector @@ to_tsquery('english', 'API')
        """)
        assert len(tenant_docs) >= 1

    def flow_7():
        """Content cache + TTL"""
        db.execute("DELETE FROM ag_brain.content_cache WHERE source_uri IN ('jira://PROJ-101', 'slack://expired')")
        
        db.execute("""
            INSERT INTO ag_brain.content_cache 
                (source_uri, owner_id, content, content_hash, ttl_seconds, source_type)
            VALUES (%s, '__tenant__', %s, 'ch1', 3600, 'jira')
        """, ("jira://PROJ-101", "Full Jira ticket content..."))
        db.execute("""
            INSERT INTO ag_brain.content_cache 
                (source_uri, owner_id, content, content_hash, ttl_seconds, source_type)
            VALUES (%s, '__tenant__', %s, 'ch2', 1, 'slack')
        """, ("slack://expired", "This should be expired"))
        
        cached = db.fetch_one("""
            SELECT * FROM ag_brain.content_cache 
            WHERE source_uri = %s AND fetched_at + (ttl_seconds * INTERVAL '1 second') > NOW()
        """, ("jira://PROJ-101",))
        assert cached is not None
        
        time.sleep(1.1)
        expired = db.fetch_one("""
            SELECT * FROM ag_brain.content_cache 
            WHERE source_uri = %s AND fetched_at + (ttl_seconds * INTERVAL '1 second') > NOW()
        """, ("slack://expired",))
        assert expired is None

    def flow_8():
        """Answer cache + hit tracking"""
        db.execute("DELETE FROM ag_brain.answer_cache WHERE question_hash = 'qh_test_1'")
        
        db.execute("""
            INSERT INTO ag_brain.answer_cache 
                (question_hash, question_text, question_keywords, answer, bundle_name, model)
            VALUES (%s, %s, %s, %s, 'general', 'claude-sonnet')
        """, ("qh_test_1", "What is our tech stack?", "tech stack",
              "We use Python, PostgreSQL, and FastAPI"))
        
        answer = db.fetch_one("""
            UPDATE ag_brain.answer_cache 
            SET hit_count = hit_count + 1, last_hit_at = NOW()
            WHERE question_hash = %s
            RETURNING answer, hit_count
        """, ("qh_test_1",))
        assert answer['hit_count'] == 1
        assert "Python" in answer['answer']

    def flow_9():
        """Entity graph + FTS"""
        db.execute("DELETE FROM ag_brain.relations")
        db.execute("DELETE FROM ag_brain.entities WHERE owner_id = '__tenant__'")
        
        e1 = db.execute_returning("""
            INSERT INTO ag_brain.entities (name, entity_type, owner_id, properties_json)
            VALUES ('Alice', 'person', '__tenant__', '{"role": "admin"}')
            RETURNING entity_id
        """)
        e2 = db.execute_returning("""
            INSERT INTO ag_brain.entities (name, entity_type, owner_id, properties_json)
            VALUES ('Agent', 'project', '__tenant__', '{"language": "python"}')
            RETURNING entity_id
        """)
        db.execute("""
            INSERT INTO ag_brain.relations (from_entity_id, to_entity_id, relation_type)
            VALUES (%s, %s, 'WORKS_ON')
        """, (e1['entity_id'], e2['entity_id']))
        
        found = db.fetch_all("""
            SELECT name, entity_type FROM ag_brain.entities
            WHERE fts_vector @@ to_tsquery('simple', 'agent')
        """)
        assert len(found) == 1, f"Expected 1 entity, got {len(found)}"
        assert found[0]['name'] == 'Agent'
        
        prefix_found = db.fetch_all("""
            SELECT name FROM ag_brain.entities
            WHERE fts_vector @@ to_tsquery('simple', 'agent:*')
        """)
        assert len(prefix_found) >= 1, "Prefix search should find Agent"
        
        related = db.fetch_all("""
            SELECT e2.name, r.relation_type
            FROM ag_brain.relations r
            JOIN ag_brain.entities e2 ON r.to_entity_id = e2.entity_id
            WHERE r.from_entity_id = %s
        """, (e1['entity_id'],))
        assert len(related) == 1
        assert related[0]['relation_type'] == 'WORKS_ON'

    def flow_10():
        """Sync state tracking"""
        db.execute("DELETE FROM ag_brain.sync_state WHERE source_key = 'jira'")
        
        db.execute("""
            INSERT INTO ag_brain.sync_state (source_key, status, docs_synced, config_json)
            VALUES ('jira', 'running', 0, '{"project": "PROJ"}')
        """)
        db.execute("""
            UPDATE ag_brain.sync_state 
            SET status = 'idle', docs_synced = 42, last_sync_at = NOW(),
                sync_cursor = 'page_token_abc'
            WHERE source_key = 'jira'
        """)
        state = db.fetch_one("SELECT * FROM ag_brain.sync_state WHERE source_key = 'jira'")
        assert state['status'] == 'idle'
        assert state['docs_synced'] == 42

    test("Flow  6: Document ingestion + FTS search", flow_6)
    test("Flow  7: Content cache + TTL expiry", flow_7)
    test("Flow  8: Answer cache + hit tracking", flow_8)
    test("Flow  9: Entity graph + FTS", flow_9)
    test("Flow 10: Sync state tracking", flow_10)
    print()

    print("── 3. Memory Flows ──")

    def flow_11():
        """Memory store + recall + FTS"""
        for user_id, key, value, layer, category in [
            (f"user_{alice['user_id']}", "alice.pref.editor", "VSCode with Vim keybindings", "semantic", "preference"),
            (f"user_{alice['user_id']}", "alice.fact.timezone", "Alice works in IST timezone", "semantic", "fact"),
            (f"user_{bob['user_id']}", "bob.pref.editor", "IntelliJ IDEA with Dracula theme", "semantic", "preference"),
            ("__tenant__", "org.stack", "Python + PostgreSQL + FastAPI", "company", "fact"),
        ]:
            db.execute("""
                INSERT INTO ag_memory.memories (user_id, key, value, layer, category)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
            """, (user_id, key, value, layer, category))
        
        alice_scopes = [f"user_{alice['user_id']}", "__tenant__"]
        alice_mems = db.fetch_all("""
            SELECT key, value, user_id FROM ag_memory.memories
            WHERE user_id = ANY(%s)
            ORDER BY key
        """, (alice_scopes,))
        assert len(alice_mems) == 3
        
        fts_results = db.fetch_all("""
            SELECT key, value, user_id FROM ag_memory.memories
            WHERE fts_vector @@ to_tsquery('english', 'VSCode')
              AND user_id = ANY(%s)
        """, (alice_scopes,))
        assert len(fts_results) == 1
        assert "Vim" in fts_results[0]['value']

    def flow_12():
        """Memory tags + filtered recall"""
        mem = db.fetch_one("""
            SELECT memory_id FROM ag_memory.memories 
            WHERE key = 'alice.pref.editor'
        """)
        for tag in ['editor', 'tools', 'development']:
            db.execute("""
                INSERT INTO ag_memory.memory_tags (memory_id, tag) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (mem['memory_id'], tag))
        
        tagged = db.fetch_all("""
            SELECT m.key, m.value, t.tag
            FROM ag_memory.memories m
            JOIN ag_memory.memory_tags t ON m.memory_id = t.memory_id
            WHERE t.tag = 'editor'
        """)
        assert len(tagged) >= 1

    def flow_13():
        """Memory entity graph (conversation)"""
        e1 = db.execute_returning("""
            INSERT INTO ag_memory.entities (name, entity_type, user_id, properties)
            VALUES ('Alice', 'person', %s, '{"title": "Admin"}')
            RETURNING entity_id
        """, (f"user_{alice['user_id']}",))
        e2 = db.execute_returning("""
            INSERT INTO ag_memory.entities (name, entity_type, user_id, properties)
            VALUES ('Database Migration', 'project', %s, '{"status": "in_progress"}')
            RETURNING entity_id
        """, (f"user_{alice['user_id']}",))
        db.execute("""
            INSERT INTO ag_memory.relations (source_id, target_id, relation_type)
            VALUES (%s, %s, 'LEADS')
        """, (e1['entity_id'], e2['entity_id']))
        
        graph = db.fetch_all("""
            SELECT e1.name as from_name, r.relation_type, e2.name as to_name
            FROM ag_memory.relations r
            JOIN ag_memory.entities e1 ON r.source_id = e1.entity_id
            JOIN ag_memory.entities e2 ON r.target_id = e2.entity_id
            WHERE e1.user_id = %s
        """, (f"user_{alice['user_id']}",))
        assert len(graph) == 1
        assert graph[0]['from_name'] == 'Alice'
        assert graph[0]['relation_type'] == 'LEADS'

    def flow_14():
        """Memory expiry cleanup"""
        db.execute("""
            INSERT INTO ag_memory.memories (user_id, key, value, layer, expires_at)
            VALUES ('expire_user', 'expired.session', 'Old session data', 'session',
                    NOW() - INTERVAL '1 hour')
        """)
        cleaned = db.fetch_scalar("SELECT ag_memory.cleanup_expired()")
        assert cleaned >= 1
        remaining = db.exists(
            "SELECT 1 FROM ag_memory.memories WHERE key = 'expired.session'")
        assert remaining == False

    test("Flow 11: Memory store + recall + FTS", flow_11)
    test("Flow 12: Memory tags + filtered recall", flow_12)
    test("Flow 13: Memory entity graph (conversation)", flow_13)
    test("Flow 14: Memory expiry cleanup", flow_14)
    print()

    print("── 4. Agent Flows ──")

    def flow_15():
        """Agent definition CRUD"""
        agent = db.execute_returning("""
            INSERT INTO ag_agents.definitions 
                (name, description, system_prompt, tools, model, 
                 schedule, owner_id, created_by)
            VALUES ('daily-digest', 'Summarize key updates', 
                    'You are a news summarizer', '["brain_search", "memory_recall"]'::jsonb,
                    'anthropic/claude-sonnet-4', '0 9 * * *', '__tenant__', %s)
            RETURNING agent_id, name
        """, (alice['user_id'],))
        assert agent['name'] == 'daily-digest'
        
        loaded = db.fetch_one(
            "SELECT * FROM ag_agents.definitions WHERE name = 'daily-digest'")
        assert loaded['tools'] == ["brain_search", "memory_recall"]
        assert loaded['schedule'] == '0 9 * * *'
        
        db.execute("""
            UPDATE ag_agents.definitions SET model = 'gpt-4o', enabled = TRUE
            WHERE name = 'daily-digest'
        """)
        updated = db.fetch_one(
            "SELECT model, updated_at FROM ag_agents.definitions WHERE name = 'daily-digest'")
        assert updated['model'] == 'gpt-4o'

    def flow_16():
        """Agent run logging"""
        agent = db.fetch_one(
            "SELECT agent_id FROM ag_agents.definitions WHERE name = 'daily-digest'")
        
        run = db.execute_returning("""
            INSERT INTO ag_agents.runs 
                (agent_id, status, input_prompt, triggered_by)
            VALUES (%s, 'running', 'Summarize today updates', %s)
            RETURNING run_id
        """, (agent['agent_id'], alice['user_id']))
        
        db.execute("""
            UPDATE ag_agents.runs 
            SET status = 'ok', output_text = 'Today: 3 PRs merged, 1 deploy, no incidents.',
                completed_at = NOW(), duration_ms = 4500, token_count = 1200
            WHERE run_id = %s
        """, (run['run_id'],))
        
        db.execute("""
            UPDATE ag_agents.definitions
            SET last_run_at = NOW(), last_status = 'ok', run_count = run_count + 1
            WHERE agent_id = %s
        """, (agent['agent_id'],))
        
        runs = db.fetch_all("""
            SELECT r.status, r.duration_ms, d.name as agent_name
            FROM ag_agents.runs r
            JOIN ag_agents.definitions d ON r.agent_id = d.agent_id
            WHERE d.name = 'daily-digest'
            ORDER BY r.started_at DESC
        """)
        assert len(runs) >= 1
        assert runs[0]['status'] == 'ok'

    def flow_17():
        """Cron job management"""
        db.execute("""
            INSERT INTO ag_agents.cron_jobs 
                (name, prompt, schedule, created_by, next_run_at)
            VALUES ('sync-jira', 'Sync all Jira tickets', '*/30 * * * *', %s,
                    NOW() + INTERVAL '30 minutes')
        """, (alice['user_id'],))
        
        db.execute("""
            UPDATE ag_agents.cron_jobs 
            SET last_run_at = NOW(), run_count = run_count + 1,
                last_status = 'ok', last_output = 'Synced 12 tickets',
                next_run_at = NOW() + INTERVAL '30 minutes'
            WHERE name = 'sync-jira'
        """)
        
        job = db.fetch_one("SELECT * FROM ag_agents.cron_jobs WHERE name = 'sync-jira'")
        assert job['run_count'] == 1
        assert job['last_status'] == 'ok'

    test("Flow 15: Agent definition CRUD", flow_15)
    test("Flow 16: Agent run logging", flow_16)
    test("Flow 17: Cron job management", flow_17)
    print()

    print("── 5. System Flows ──")

    def flow_18():
        """Config get/set"""
        db.set_config("test.flow18", "hello", description="Test config")
        assert db.get_config("test.flow18") == "hello"
        db.set_config("test.flow18", "updated")
        assert db.get_config("test.flow18") == "updated"
        llm = db.get_configs("llm.")
        assert len(llm) >= 4
        assert "llm.provider" in llm
        db.execute("DELETE FROM ag_system.configs WHERE config_key = 'test.flow18'")

    def flow_19():
        """Integration CRUD"""
        db.upsert_integration("outlook", "Microsoft Outlook",
            config={"tenant_id": "abc-123", "scopes": ["mail.read"]},
            is_enabled=True)
        outlook = db.get_integration("outlook")
        assert outlook['status'] == 'active'
        assert outlook['config_json']['tenant_id'] == 'abc-123'
        db.execute("""
            UPDATE ag_system.integrations 
            SET is_enabled = FALSE, status = 'revoked'
            WHERE service_key = 'outlook'
        """)
        updated = db.get_integration("outlook")
        assert updated['status'] == 'revoked'

    def flow_20():
        """Audit trail"""
        db.audit("brain.ingest", "document", "jira://PROJ-101", 
                 alice['user_id'], {"source": "jira", "docs": 3}, "10.0.0.1")
        db.audit("auth.login", "user", str(bob['user_id']),
                 bob['user_id'], {"platform": "telegram"})
        
        entries = db.fetch_all("""
            SELECT action, entity_type, details_json 
            FROM ag_system.audit_log 
            WHERE action LIKE 'brain.%' OR action LIKE 'auth.%'
            ORDER BY created_at DESC
        """)
        assert len(entries) >= 2

    def flow_21():
        """Conversation summaries"""
        db.execute("""
            INSERT INTO ag_system.conversation_summaries 
                (user_id, session_id, summary, message_count, started_at, ended_at)
            VALUES (%s, 'sess_001', 'Discussed database migration and agent architecture.',
                    15, NOW() - INTERVAL '1 hour', NOW())
        """, (alice['user_id'],))
        
        summaries = db.fetch_all("""
            SELECT * FROM ag_system.conversation_summaries 
            WHERE user_id = %s ORDER BY created_at DESC
        """, (alice['user_id'],))
        assert len(summaries) >= 1
        assert "migration" in summaries[0]['summary']

    def flow_22():
        """Tenant stats dashboard"""
        stats = db.get_tenant_stats()
        assert stats['active_users'] >= 3
        assert stats['total_documents'] >= 3
        assert stats['total_memories'] >= 4
        assert stats['active_agents'] >= 1
        assert 'kB' in stats['db_size'] or 'MB' in stats['db_size']

    def flow_23():
        """Migration history"""
        migrations = db.fetch_all(
            "SELECT version, script_name FROM ag_system.migration_history ORDER BY version")
        assert len(migrations) >= 2
        assert migrations[0]['version'] == 'V001'
        assert migrations[1]['version'] == 'V002'

    test("Flow 18: Config get/set + prefix", flow_18)
    test("Flow 19: Integration CRUD", flow_19)
    test("Flow 20: Audit trail", flow_20)
    test("Flow 21: Conversation summaries", flow_21)
    test("Flow 22: Tenant stats dashboard", flow_22)
    test("Flow 23: Migration history", flow_23)
    print()

    print("── 6. Cross-cutting Flows ──")

    def flow_24():
        """Scope isolation — user A can't see user B's data"""
        alice_scope = [f"user_{alice['user_id']}", "__tenant__"]
        bob_scope = [f"user_{bob['user_id']}", "__tenant__"]
        
        alice_mems = db.fetch_all("""
            SELECT key FROM ag_memory.memories WHERE user_id = ANY(%s)
        """, (alice_scope,))
        alice_keys = [m['key'] for m in alice_mems]
        
        bob_mems = db.fetch_all("""
            SELECT key FROM ag_memory.memories WHERE user_id = ANY(%s)
        """, (bob_scope,))
        bob_keys = [m['key'] for m in bob_mems]
        
        assert "alice.pref.editor" in alice_keys
        assert "org.stack" in alice_keys
        assert "bob.pref.editor" not in alice_keys
        
        assert "bob.pref.editor" in bob_keys
        assert "org.stack" in bob_keys
        assert "alice.pref.editor" not in bob_keys
        
        alice_docs = db.fetch_all("""
            SELECT title FROM ag_brain.documents WHERE owner_id = ANY(%s)
        """, (alice_scope,))
        alice_titles = [d['title'] for d in alice_docs]
        assert "Meeting Notes" in alice_titles
        assert "API Redesign" in alice_titles
        
        bob_docs = db.fetch_all("""
            SELECT title FROM ag_brain.documents WHERE owner_id = ANY(%s)
        """, (bob_scope,))
        bob_titles = [d['title'] for d in bob_docs]
        assert "Meeting Notes" not in bob_titles
        assert "API Redesign" in bob_titles

    def flow_25():
        """updated_at triggers fire on UPDATE"""
        mem = db.fetch_one("""
            SELECT memory_id, updated_at FROM ag_memory.memories 
            WHERE key = 'org.stack'
        """)
        old_ts = mem['updated_at']
        time.sleep(0.05)
        db.execute("""
            UPDATE ag_memory.memories SET value = 'Python + PG + FastAPI v2' 
            WHERE memory_id = %s
        """, (mem['memory_id'],))
        new = db.fetch_one("""
            SELECT updated_at FROM ag_memory.memories WHERE memory_id = %s
        """, (mem['memory_id'],))
        assert new['updated_at'] > old_ts

    test("Flow 24: Scope isolation (user A ↮ user B)", flow_24)
    test("Flow 25: updated_at triggers", flow_25)
    print()

    print("── Cleanup ──")
    db.execute("DELETE FROM ag_agents.runs")
    db.execute("DELETE FROM ag_agents.cron_jobs")
    db.execute("DELETE FROM ag_agents.definitions")
    db.execute("DELETE FROM ag_brain.relations")
    db.execute("DELETE FROM ag_brain.entities")
    db.execute("DELETE FROM ag_brain.ingestion_log")
    db.execute("DELETE FROM ag_brain.documents")
    db.execute("DELETE FROM ag_brain.content_cache")
    db.execute("DELETE FROM ag_brain.answer_cache")
    db.execute("DELETE FROM ag_brain.sync_state")
    db.execute("DELETE FROM ag_memory.relations")
    db.execute("DELETE FROM ag_memory.entities")
    db.execute("DELETE FROM ag_memory.memory_tags")
    db.execute("DELETE FROM ag_memory.memories")
    db.execute("DELETE FROM ag_system.conversation_summaries")
    db.execute("DELETE FROM ag_system.integrations")
    db.execute("DELETE FROM ag_system.audit_log WHERE action NOT LIKE 'system.%'")
    db.execute("DELETE FROM ag_auth.user_sessions")
    db.execute("DELETE FROM ag_auth.refresh_tokens")
    db.execute("DELETE FROM ag_auth.user_permission_overrides")
    db.execute("DELETE FROM ag_auth.api_keys")
    db.execute("DELETE FROM ag_auth.users WHERE external_id LIKE 'test_%'")
    print("  All test data cleaned up")
    print()

    print(f"{'═' * 65}")
    if failed == 0:
        print(f"  🎯 ALL {passed} FLOWS PASSED")
    else:
        print(f"  ⚠️  {passed} PASSED, {failed} FAILED")
        for name, err in errors:
            print(f"     ❌ {name}: {err}")
    print(f"{'═' * 65}")
    
    db.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
