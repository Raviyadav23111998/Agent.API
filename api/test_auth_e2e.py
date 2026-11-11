"""
AGENT.API — Auth E2E Test Suite
================================
Tests all auth endpoints identical to SMSystems.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import requests

BASE = 'http://localhost:8100'
passed = 0
failed = 0

def test(num, label):
    """Decorator for test functions."""
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


tokens = {}

print('═' * 65)
print('  AGENT.API — Auth E2E Test')
print('═' * 65)
print()

try:
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'demo', 'password': 'Demo@123', 'grantType': 'client_credentials'
    })
    if r.status_code != 200:
        r = requests.post(f'{BASE}/Login', json={
            'userName': 'demo', 'password': 'NewPass@456', 'grantType': 'client_credentials'
        })
        if r.status_code == 200:
            tok = r.json()['accessToken']
            requests.post(f'{BASE}/ChangePassword', json={
                'requestType': 'ResetPassword', 'password': 'Demo@123', 'accessToken': tok
            })
            print('  (restored demo password)')
except:
    pass

@test(1, 'GET / → AGENT.API')
def _():
    r = requests.get(f'{BASE}/')
    assert r.status_code == 200 and r.json()['service'] == 'AGENT.API'

@test(2, 'Health → healthy + db_connected')
def _():
    r = requests.get(f'{BASE}/health')
    assert r.status_code == 200 and r.json()['db_connected']

@test(3, 'Login admin (client_credentials)')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'admin', 'password': 'Admin@123', 'grantType': 'client_credentials'
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['user']['username'] == 'admin'
    assert d['user']['role'] == 'Administrator'
    tokens['admin_at'] = d['accessToken']
    tokens['admin_rt'] = d['refreshToken']

@test(4, 'Bad password → 401')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'admin', 'password': 'wrong', 'grantType': 'client_credentials'
    })
    assert r.status_code == 401

@test(5, 'Unknown user → 401')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'nobody', 'password': 'x', 'grantType': 'client_credentials'
    })
    assert r.status_code == 401

@test(6, 'Logout no token → 401')
def _():
    r = requests.get(f'{BASE}/Logout')
    assert r.status_code in [401, 403]

@test(7, 'Logout with token → 200')
def _():
    r = requests.get(f'{BASE}/Logout', headers={
        'Authorization': f'Bearer {tokens["admin_at"]}'
    })
    assert r.status_code == 200

@test(8, 'Login demo → Demo User')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'demo', 'password': 'Demo@123', 'grantType': 'client_credentials'
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['user']['display_name'] == 'Demo User'
    tokens['mm_at'] = d['accessToken']
    tokens['mm_rt'] = d['refreshToken']

@test(9, 'Refresh token → new token issued')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'grantType': 'refresh_token',
        'token': {'token': tokens['mm_at'], 'refreshToken': tokens['mm_rt']}
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['accessToken'] != tokens['mm_at'], 'Should be a NEW token'
    tokens['mm_at2'] = d['accessToken']
    tokens['mm_rt2'] = d['refreshToken']

@test(10, 'Bad refresh token → 401')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'grantType': 'refresh_token',
        'token': {'token': tokens['mm_at'], 'refreshToken': 'bogus_invalid'}
    })
    assert r.status_code == 401

@test(11, 'Invalid grant type → 422/401')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'x', 'password': 'x', 'grantType': 'invalid'
    })
    assert r.status_code in [401, 422], f'Expected 401/422, got {r.status_code}'

@test(12, 'Swagger docs → 200')
def _():
    r = requests.get(f'{BASE}/swagger')
    assert r.status_code == 200

@test(13, 'JWT claims match SMSystems (RS256, 7 claims)')
def _():
    import jwt as pyjwt
    tok = tokens.get('mm_at2', tokens['mm_at'])
    p = pyjwt.decode(tok, options={'verify_signature': False})
    for claim in ['user_ID', 'user_code', 'email_ID', 'role', 'session_ID', 'tenant_id']:
        assert claim in p, f'Missing claim: {claim}'
    assert p['iss'] == 'Storeglance.MSystem'
    assert p['aud'] == 'Storeglance.SolutionsKraft'

@test(14, 'RSA verify (shared with SMSystems/Fleet)')
def _():
    from core.config import app_config
    app_config.load('postgresql://agent_uat_user:ag3nt_uat_s3cure_2024@localhost:15432/agent_uat')
    from api.middleware.auth import verify_jwt_token
    tok = tokens.get('mm_at2', tokens['mm_at'])
    v = verify_jwt_token(tok, app_config.get('secret.public_key'),
                         'Storeglance.MSystem', 'Storeglance.SolutionsKraft')
    assert v['user_code'] == 'demo'
    app_config.close()

@test(15, 'DB records (sessions, tokens, audit)')
def _():
    from core.tenant_db import TenantDB
    db = TenantDB('postgresql://agent_uat_user:ag3nt_uat_s3cure_2024@localhost:15432/agent_uat')
    db.connect()
    s = db.fetch_one('SELECT count(*) as cnt FROM ag_auth.user_sessions')
    t = db.fetch_one('SELECT count(*) as cnt FROM ag_auth.refresh_tokens')
    a = db.fetch_one("SELECT count(*) as cnt FROM ag_system.audit_log WHERE entity_type='auth'")
    db.close()
    assert s['cnt'] > 0 and t['cnt'] > 0 and a['cnt'] > 0

@test(16, 'ChangePassword → reset + verify + restore')
def _():
    tok = tokens.get('mm_at2', tokens['mm_at'])
    r = requests.post(f'{BASE}/ChangePassword', json={
        'requestType': 'ResetPassword', 'password': 'NewPass@456', 'accessToken': tok
    })
    assert r.status_code == 200
    cp = r.json()
    assert cp.get('is_success') or cp.get('isSuccess'), f'Not success: {cp}'
    r2 = requests.post(f'{BASE}/Login', json={
        'userName': 'demo', 'password': 'NewPass@456', 'grantType': 'client_credentials'
    })
    assert r2.status_code == 200, f'Login with new password failed: {r2.text}'
    r3 = requests.post(f'{BASE}/ChangePassword', json={
        'requestType': 'ResetPassword', 'password': 'Demo@123',
        'accessToken': r2.json()['accessToken']
    })
    assert r3.status_code == 200

print()
print('═' * 65)
print(f'  🎯 {passed}/{passed + failed} AUTH TESTS PASSED')
if failed == 0:
    print('  ✅ Phase 1 Complete — Auth identical to SMSystems')
    print('  Endpoints: POST /Login, GET /Logout, POST /ChangePassword')
    print('  JWT: RS256 (same RSA keys as SMSystems/Fleet)')
    print('  Claims: user_ID, user_code, email_ID, role, session_ID, tenant_id')
    print('  Grant types: client_credentials, refresh_token')
print('═' * 65)

sys.exit(0 if failed == 0 else 1)
