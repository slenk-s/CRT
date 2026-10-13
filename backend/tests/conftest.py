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
os.environ.setdefault("SMB_ROOT", "slenk_\\FA_ROOT")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_storage  # noqa: E402
from app.routers import changeover as _changeover_router  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402
from app.main import app  # noqa: E402
from fakes import FakeStorage, BrokenSmbStorage  # noqa: E402


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
    _changeover_router._test_smb_storage = fake
    yield fake
    app.dependency_overrides.pop(get_storage, None)
    _changeover_router._test_smb_storage = None


@pytest.fixture()
def offline_storage(monkeypatch):
    """SMB 完全离线：BrokenSmb 拦截所有写，Local 落临时目录。

    路由层与后台同步服务共用同一套替身，并显式给出 SMB 配置，
    保证测试既不会真的去连内网共享盘，也不会因"未配置"被提前跳过。

    返回 dict：{"smb": BrokenSmbStorage, "local": LocalStorage}。
    注意：get_storage 依赖不覆盖（因为 delete_changeover 只会在 synced=1 时
    调 storage.remove，而离线态全是 synced=0，不会触发真实 SMB 连接）。
    """
    import tempfile
    import shutil
    import app.services.sync as sync_svc
    from app import config as _config

    tmp = tempfile.mkdtemp(prefix="co_offline_")
    local = LocalStorage(tmp)
    smb = BrokenSmbStorage()
    monkeypatch.setattr(_changeover_router, "_test_smb_storage", smb)
    monkeypatch.setattr(_changeover_router, "_test_local_storage", local)
    monkeypatch.setattr(sync_svc, "SmbStorage", lambda: smb)
    monkeypatch.setattr(_config, "SMB_HOST", "10.0.0.1")
    monkeypatch.setattr(_config, "SMB_SHARE", "pub")
    monkeypatch.setattr(_config, "LOCAL_PHOTO_DIR", tmp)
    yield {"smb": smb, "local": local, "root": tmp}
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def line_auth(client, auth):
    """建一个普通（line）角色账号并返回其认证头，用于权限测试。"""
    client.post("/api/admin/users",
                json={"emp_id": "T90001", "name": "测试线体员", "password": "Line@12345",
                      "role": "line"}, headers=auth)
    r = client.post("/api/auth/login", json={"emp_id": "T90001", "password": "Line@12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}