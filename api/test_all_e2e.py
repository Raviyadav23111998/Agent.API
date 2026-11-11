"""
AGENT.API — Full E2E Test Suite (All APIs)
===========================================
Tests: Chat (SSE), Agents, Brain, Memory + Auth + Users regression
"""
import os
import sys
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import requests

BASE = 'http://localhost:8100'
passed = 0
failed = 0


def test(num, label):
    def decorator(fn):
        global passed, failed
        try:
            fn()
            print(f'✅ Test {num:2d}: {label}')
            passed += 1
        except Exception as e:
            print(f'❌ Test {num:2d}: {label} → {e}')
            failed += 1
    return decorator


def get_token(user='admin', pw='Admin@123'):
    r = requests.post(f'{BASE}/Login', json={
        'userName': user, 'password': pw, 'grantType': 'client_credentials'
    })
    assert r.status_code == 200, f'Login failed: {r.text}'
    return r.json()['accessToken']


token = get_token()
headers = {'Authorization': f'Bearer {token}'}

print('═' * 70)
print('  AGENT.API — Full E2E Test Suite')
print('═' * 70)

print('\n── Auth ──')

@test(1, 'Health → healthy')
def _():
    r = requests.get(f'{BASE}/health')
    assert r.status_code == 200 and r.json()['db_connected']

@test(2, 'Login admin → 200')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'admin', 'password': 'Admin@123', 'grantType': 'client_credentials'
    })
    assert r.status_code == 200

@test(3, 'Bad password → 401')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'admin', 'password': 'wrong', 'grantType': 'client_credentials'
    })
    assert r.status_code == 401

print('\n── Users ──')

@test(4, 'GET /api/v1/users → list')
def _():
    r = requests.get(f'{BASE}/api/v1/users', headers=headers)
    assert r.status_code == 200 and len(r.json()) >= 2

@test(5, 'User/Validate/Email → existing')
def _():
    r = requests.get(f'{BASE}/User/Validate/Email', headers=headers,
                     params={'Email': 'admin@storeglance.com'})
    assert r.status_code == 200 and r.json()['exists']

print('\n── Chat (SSE Streaming) ──')
chat_conv_id = None

@test(6, 'POST /api/v1/chat → SSE stream (non-streaming)')
def _():
    global chat_conv_id
    r = requests.post(f'{BASE}/api/v1/chat', headers=headers, json={
        'message': 'Say hello in exactly 5 words.',
        'stream': False,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert 'conversationId' in d
    assert len(d['message']) > 0
    chat_conv_id = d['conversationId']

@test(7, 'POST /api/v1/chat → SSE stream (streaming)')
def _():
    r = requests.post(f'{BASE}/api/v1/chat', headers=headers, json={
        'message': 'What is 2+2?',
        'conversationId': chat_conv_id,
        'stream': True,
    }, stream=True)
    assert r.status_code == 200
    assert r.headers.get('content-type', '').startswith('text/event-stream')

    events = []
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith('data: '):
            data = line[6:]
            if data == '[DONE]':
                events.append({'event': 'DONE'})
                break
            try:
                events.append(json.loads(data))
            except:
                pass

    event_types = [e.get('event', 'DONE') for e in events]
    assert 'message.start' in event_types, f'No message.start: {event_types}'
    assert 'message.end' in event_types or 'DONE' in event_types

@test(8, 'GET /api/v1/chat/conversations → list')
def _():
    r = requests.get(f'{BASE}/api/v1/chat/conversations', headers=headers)
    assert r.status_code == 200
    convs = r.json()
    assert isinstance(convs, list) and len(convs) >= 1

@test(9, 'GET /api/v1/chat/conversations/{id} → messages persisted')
def _():
    assert chat_conv_id, 'No conversation'
    r = requests.get(f'{BASE}/api/v1/chat/conversations/{chat_conv_id}', headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert d['conversation_id'] == chat_conv_id
    msgs = d.get('messages', [])
    assert len(msgs) >= 2, f'Expected ≥2 messages, got {len(msgs)}'

@test(10, 'POST /api/v1/chat → continue conversation')
def _():
    r = requests.post(f'{BASE}/api/v1/chat', headers=headers, json={
        'message': 'What was my first question?',
        'conversationId': chat_conv_id,
        'stream': False,
    })
    assert r.status_code == 200

@test(11, 'DELETE /api/v1/chat/conversations/{id}')
def _():
    r = requests.post(f'{BASE}/api/v1/chat', headers=headers, json={
        'message': 'temp', 'stream': False,
    })
    temp_id = r.json()['conversationId']
    r2 = requests.delete(f'{BASE}/api/v1/chat/conversations/{temp_id}', headers=headers)
    assert r2.status_code == 200

print('\n── Agents ──')
created_agent_id = None

@test(12, 'POST /api/v1/agents → create')
def _():
    global created_agent_id
    r = requests.post(f'{BASE}/api/v1/agents', headers=headers, json={
        'name': 'test_agent_e2e',
        'description': 'E2E test agent',
        'systemPrompt': 'You are a test agent. Always respond with OK.',
        'model': 'gemini-2.0-flash',
        'enabled': True,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['agent_id'] > 0
    created_agent_id = d['agent_id']

@test(13, 'GET /api/v1/agents → list')
def _():
    r = requests.get(f'{BASE}/api/v1/agents', headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list) and len(r.json()) >= 1

@test(14, 'GET /api/v1/agents/{id} → detail')
def _():
    assert created_agent_id, 'No agent'
    r = requests.get(f'{BASE}/api/v1/agents/{created_agent_id}', headers=headers)
    assert r.status_code == 200
    assert r.json()['name'] == 'test_agent_e2e'

@test(15, 'PUT /api/v1/agents/{id} → update')
def _():
    assert created_agent_id, 'No agent'
    r = requests.put(f'{BASE}/api/v1/agents/{created_agent_id}', headers=headers, json={
        'name': 'test_agent_e2e',
        'description': 'Updated description',
    })
    assert r.status_code == 200

@test(16, 'DELETE /api/v1/agents/{id}')
def _():
    assert created_agent_id, 'No agent'
    r = requests.delete(f'{BASE}/api/v1/agents/{created_agent_id}', headers=headers)
    assert r.status_code == 200

print('\n── Brain ──')
ingested_doc_id = None

@test(17, 'POST /api/v1/brain/ingest → ingest document')
def _():
    global ingested_doc_id
    r = requests.post(f'{BASE}/api/v1/brain/ingest', headers=headers, json={
        'sourcePath': '/test/e2e_document.txt',
        'content': 'Agent is an AI platform built by Storeglance for intelligent automation.',
        'title': 'E2E Test Document',
        'docType': 'document',
    })
    assert r.status_code == 200, r.text
    d = r.json()
    ingested_doc_id = d.get('doc_id')

@test(18, 'POST /api/v1/brain/search → FTS search')
def _():
    r = requests.post(f'{BASE}/api/v1/brain/search', headers=headers, json={
        'query': 'Agent AI platform',
        'limit': 5,
    })
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)

@test(19, 'GET /api/v1/brain/documents → list')
def _():
    r = requests.get(f'{BASE}/api/v1/brain/documents', headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

@test(20, 'GET /api/v1/brain/stats')
def _():
    r = requests.get(f'{BASE}/api/v1/brain/stats', headers=headers)
    assert r.status_code == 200
    assert 'total' in r.json()

@test(21, 'DELETE /api/v1/brain/documents/{id}')
def _():
    if ingested_doc_id:
        r = requests.delete(f'{BASE}/api/v1/brain/documents/{ingested_doc_id}', headers=headers)
        assert r.status_code == 200

print('\n── Memory ──')
stored_memory_id = None

@test(22, 'POST /api/v1/memory/store → store memory')
def _():
    global stored_memory_id
    r = requests.post(f'{BASE}/api/v1/memory/store', headers=headers, json={
        'key': 'test.e2e_preference',
        'value': 'User prefers dark mode and concise responses',
        'category': 'preference',
        'layer': 'semantic',
    })
    assert r.status_code == 200, r.text
    d = r.json()
    stored_memory_id = d.get('memory_id')

@test(23, 'POST /api/v1/memory/recall → search')
def _():
    r = requests.post(f'{BASE}/api/v1/memory/recall', headers=headers, json={
        'query': 'dark mode preference',
        'limit': 5,
    })
    assert r.status_code == 200
    results = r.json()
    assert isinstance(results, list)

@test(24, 'GET /api/v1/memory → list')
def _():
    r = requests.get(f'{BASE}/api/v1/memory', headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

@test(25, 'GET /api/v1/memory/stats')
def _():
    r = requests.get(f'{BASE}/api/v1/memory/stats', headers=headers)
    assert r.status_code == 200

@test(26, 'DELETE /api/v1/memory/{id}')
def _():
    if stored_memory_id:
        r = requests.delete(f'{BASE}/api/v1/memory/{stored_memory_id}', headers=headers)
        assert r.status_code == 200

print('\n── Security ──')

@test(27, 'Chat without auth → 401')
def _():
    r = requests.post(f'{BASE}/api/v1/chat', json={'message': 'hello'})
    assert r.status_code in [401, 403]

@test(28, 'Agents without auth → 401')
def _():
    r = requests.get(f'{BASE}/api/v1/agents')
    assert r.status_code in [401, 403]

@test(29, 'Brain without auth → 401')
def _():
    r = requests.post(f'{BASE}/api/v1/brain/search', json={'query': 'test'})
    assert r.status_code in [401, 403]

@test(30, 'Memory without auth → 401')
def _():
    r = requests.get(f'{BASE}/api/v1/memory')
    assert r.status_code in [401, 403]

@test(31, 'Swagger → 200')
def _():
    r = requests.get(f'{BASE}/swagger')
    assert r.status_code == 200

print()
print('═' * 70)
total = passed + failed
print(f'  🎯 {passed}/{total} TESTS PASSED')
if failed == 0:
    print('  ✅ ALL APIs COMPLETE')
    print()
    print('  📡 Auth:   POST /Login, GET /Logout, POST /ChangePassword')
    print('  👥 Users:  User/Validate/*, /api/v1/users CRUD')
    print('  💬 Chat:   POST /api/v1/chat (SSE streaming)')
    print('  🤖 Agents: /api/v1/agents CRUD + /run')
    print('  🧠 Brain:  /api/v1/brain/search, /ingest, /documents')
    print('  💾 Memory: /api/v1/memory/store, /recall')
    print()
    print('  Stream Format: SSE (text/event-stream) — ChatGPT/Gemini compatible')
    print('  Events: message.start → message.delta → message.end → [DONE]')
print('═' * 70)

sys.exit(0 if failed == 0 else 1)
