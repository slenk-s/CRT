"""pytest 全局夹具：在导入 app 之前注入测试环境变量。"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="co_test_"))

os.environ.setdefault("DB_PATH", str(_TMP / "test.db"))
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SEED_ADMIN_EMP_ID", "00660301")
os.environ.setdefault("SEED_ADMIN_NAME", "苏金炜")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "Init@12345")
os.environ.setdefault("MAX_IMAGE_MB", "5")
os.environ.setdefault("WB_SOURCE", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_storage  # noqa: E402
from app.main import app  # noqa: E402
from fakes import FakeStorage  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def token(client):
    r = client.post("/api/auth/login", json={"emp_id": "00660301", "password": "Init@12345"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fake_storage():
    """内存存储替身（覆盖 get_storage 依赖，测试不接触内网）。"""
    fake = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture(scope="session")
def line_auth(client, auth):
    """建一个普通（line）角色账号并返回其认证头，用于权限测试。"""
    client.post("/api/admin/users",
                json={"emp_id": "T90001", "name": "测试线体员", "password": "Line@12345",
                      "role": "line"}, headers=auth)
    r = client.post("/api/auth/login", json={"emp_id": "T90001", "password": "Line@12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}