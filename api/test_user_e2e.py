"""
AGENT.API — User E2E Test Suite
================================
Tests all User endpoints identical to SMSystems UserController.
"""

import os
import sys
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


def get_token(username='admin', password='Admin@123'):
    r = requests.post(f'{BASE}/Login', json={
        'userName': username, 'password': password, 'grantType': 'client_credentials'
    })
    assert r.status_code == 200, f'Login failed: {r.text}'
    return r.json()['accessToken']


try:
    tok = get_token()
    hdr = {'Authorization': f'Bearer {tok}'}
    from core.tenant_db import TenantDB
    db = TenantDB('postgresql://agent_uat_user:ag3nt_uat_s3cure_2024@localhost:15432/agent_uat')
    db.connect()
    db.execute("DELETE FROM ag_auth.user_sessions WHERE user_id IN (SELECT user_id FROM ag_auth.users WHERE user_code = 'testuser_e2e')")
    db.execute("DELETE FROM ag_auth.refresh_tokens WHERE user_id IN (SELECT user_id FROM ag_auth.users WHERE user_code = 'testuser_e2e')")
    db.execute("DELETE FROM ag_auth.users WHERE user_code = 'testuser_e2e'")
    db.close()
except:
    pass

token = get_token()
headers = {'Authorization': f'Bearer {token}'}
created_user_id = None

print('═' * 65)
print('  AGENT.API — User E2E Test')
print('═' * 65)
print()


@test(1, 'GET /api/v1/users → list all')
def _():
    r = requests.get(f'{BASE}/api/v1/users', headers=headers)
    assert r.status_code == 200
    users = r.json()
    assert isinstance(users, list) and len(users) >= 2
    assert all('userCode' in u for u in users)


@test(2, 'GET /api/v1/users/{id} → admin detail')
def _():
    r = requests.get(f'{BASE}/api/v1/users', headers=headers)
    admin = [u for u in r.json() if u['userCode'] == 'admin'][0]
    r2 = requests.get(f'{BASE}/api/v1/users/{admin["userId"]}', headers=headers)
    assert r2.status_code == 200
    d = r2.json()
    assert d['userCode'] == 'admin'
    assert d['roleName'] == 'Administrator'


@test(3, 'GET /api/v1/users/99999 → 404')
def _():
    r = requests.get(f'{BASE}/api/v1/users/99999', headers=headers)
    assert r.status_code == 404


@test(4, 'POST /api/v1/users → create testuser')
def _():
    global created_user_id
    r = requests.post(f'{BASE}/api/v1/users', headers=headers, json={
        'userCode': 'testuser_e2e', 'email': 'testuser@example.com',
        'fullName': 'Test User E2E', 'roleId': 3, 'isActive': True,
        'password': 'TestPass@123',
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d['userId'] > 0
    created_user_id = d['userId']


@test(5, 'GET /api/v1/users/{id} → created user detail')
def _():
    assert created_user_id, 'No user created'
    r = requests.get(f'{BASE}/api/v1/users/{created_user_id}', headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert d['userCode'] == 'testuser_e2e'
    assert d['fullName'] == 'Test User E2E'
    assert d['roleName'] == 'Member'


@test(6, 'POST /Login → testuser can login')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'testuser_e2e', 'password': 'TestPass@123', 'grantType': 'client_credentials'
    })
    assert r.status_code == 200


@test(7, 'PUT /api/v1/users/{id} → update testuser')
def _():
    assert created_user_id, 'No user created'
    r = requests.put(f'{BASE}/api/v1/users/{created_user_id}', headers=headers, json={
        'userCode': 'testuser_e2e', 'email': 'updated@example.com',
        'fullName': 'Updated User E2E', 'roleId': 3, 'isActive': True,
    })
    assert r.status_code == 200
    r2 = requests.get(f'{BASE}/api/v1/users/{created_user_id}', headers=headers)
    assert r2.json()['email'] == 'updated@example.com'
    assert r2.json()['fullName'] == 'Updated User E2E'


@test(8, 'PUT without password → preserves hash')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'testuser_e2e', 'password': 'TestPass@123', 'grantType': 'client_credentials'
    })
    assert r.status_code == 200, 'Password was overwritten!'


@test(9, 'GET User/Validate/Email → existing')
def _():
    r = requests.get(f'{BASE}/api/v1/users/Validate/Email', headers=headers,
                     params={'email': 'admin@storeglance.com'})
    assert r.status_code == 200 and r.json()['exists'] == True


@test(10, 'GET User/Validate/Email → new')
def _():
    r = requests.get(f'{BASE}/api/v1/users/Validate/Email', headers=headers,
                     params={'email': 'unique_noexist@example.com'})
    assert r.status_code == 200 and r.json()['exists'] == False


@test(11, 'GET User/Validate/UserCode → existing')
def _():
    r = requests.get(f'{BASE}/api/v1/users/Validate/UserCode', headers=headers,
                     params={'userCode': 'admin'})
    assert r.status_code == 200 and r.json()['exists'] == True


@test(12, 'GET User/Validate/UserCode → exclude self')
def _():
    r = requests.get(f'{BASE}/api/v1/users', headers=headers)
    admin = [u for u in r.json() if u['userCode'] == 'admin'][0]
    r2 = requests.get(f'{BASE}/api/v1/users/Validate/UserCode', headers=headers,
                      params={'userCode': 'admin', 'userId': admin['userId']})
    assert r2.status_code == 200 and r2.json()['exists'] == False


@test(13, 'GET /api/v1/users/ddl → search')
def _():
    r = requests.get(f'{BASE}/api/v1/users/ddl', headers=headers,
                     params={'SearchText': 'Admin'})
    assert r.status_code == 200
    assert isinstance(r.json(), list) and len(r.json()) >= 1


@test(14, 'GET /api/v1/users/by-ids → bulk lookup')
def _():
    assert created_user_id, 'No user'
    r = requests.get(f'{BASE}/api/v1/users/by-ids', headers=headers,
                     params={'UserIDs': str(created_user_id)})
    assert r.status_code == 200 and len(r.json()) >= 1


@test(15, 'GET User/ActiveSession → sessions')
def _():
    r = requests.get(f'{BASE}/api/v1/users/ActiveSession', headers=headers)
    assert r.status_code == 200 and isinstance(r.json(), list)


@test(16, 'GET User/InActiveSession → sessions')
def _():
    r = requests.get(f'{BASE}/api/v1/users/InActiveSession', headers=headers)
    assert r.status_code == 200 and isinstance(r.json(), list)


@test(17, 'GET /api/v1/users → no auth → 401')
def _():
    r = requests.get(f'{BASE}/api/v1/users')
    assert r.status_code in [401, 403]


@test(18, 'DELETE /api/v1/users/{id} → deactivate')
def _():
    assert created_user_id, 'No user'
    r = requests.delete(f'{BASE}/api/v1/users/{created_user_id}', headers=headers)
    assert r.status_code == 200
    r2 = requests.get(f'{BASE}/api/v1/users/{created_user_id}', headers=headers)
    assert r2.json()['isActive'] == False


@test(19, 'POST /Login → deactivated → 401')
def _():
    r = requests.post(f'{BASE}/Login', json={
        'userName': 'testuser_e2e', 'password': 'TestPass@123', 'grantType': 'client_credentials'
    })
    assert r.status_code == 401


@test(20, 'DELETE self → 400')
def _():
    import jwt as pyjwt
    p = pyjwt.decode(token, options={'verify_signature': False})
    my_id = int(p['user_ID'])
    r = requests.delete(f'{BASE}/api/v1/users/{my_id}', headers=headers)
    assert r.status_code == 400


print()
print('═' * 65)
total = passed + failed
print(f'  🎯 {passed}/{total} USER TESTS PASSED')
if failed == 0:
    print('  ✅ Users API — identical to SMSystems UserController')
    print('  SMSystems paths: User/Validate/*, User/*Session')
    print('  REST CRUD: /api/v1/users (list, get, create, update, delete)')
    print('  Features: UPSERT, password hashing, DDL search, sessions')
print('═' * 65)

sys.exit(0 if failed == 0 else 1)
