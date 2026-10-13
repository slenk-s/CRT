"""阶段 2 冒烟测试：健康检查 / 认证 / 字典。"""


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["version"]


def test_dict_requires_auth(client):
    assert client.get("/api/dict/lines").status_code == 401


def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"emp_id": "00660301", "password": "wrong"})
    assert r.status_code == 401


def test_login_and_me(client, auth):
    me = client.get("/api/auth/me", headers=auth)
    assert me.status_code == 200
    assert me.json()["emp_id"] == "00660301"
    assert me.json()["role"] == "admin"


SEED_LINES = (["1F0%d" % i for i in range(1, 8)] + ["2F0%d" % i for i in range(1, 9)]
              + ["3F0%d" % i for i in range(1, 6)] + ["4F0%d" % i for i in range(1, 6)]
              + ["7F0%d" % i for i in range(1, 5)])
SEED_STATIONS = ["DeMura工位", "耐压工位", "画检工位", "白平衡工位", "检P1工位", "AV工位",
                 "侧标工位", "复位工位", "开机工位", "检P2工位", "纸箱下线工位"]


def test_lines_seeded(client, auth):
    body = client.get("/api/dict/lines", headers=auth).json()
    lines = {x["line"] for x in body["items"]}
    assert set(SEED_LINES) <= lines and len(SEED_LINES) == 29
    assert {"一车间", "二车间", "三车间", "四车间", "七车间"} <= set(body["by_workshop"])


def test_stations_and_checkitems(client, auth):
    stations = {x["station"] for x in client.get("/api/dict/stations", headers=auth).json()}
    assert set(SEED_STATIONS) <= stations and len(SEED_STATIONS) == 11
    assert len(client.get("/api/dict/check-items", headers=auth).json()) >= 58
    wb = client.get("/api/dict/check-items", params={"station": "白平衡工位"}, headers=auth).json()
    assert len(wb) >= 15


def test_change_password_flow(client, auth):
    same = client.post(
        "/api/auth/change-password",
        json={"old_password": "Init@12345", "new_password": "Init@12345"},
        headers=auth,
    )
    assert same.status_code == 400
    ok = client.post(
        "/api/auth/change-password",
        json={"old_password": "Init@12345", "new_password": "Init@99999"},
        headers=auth,
    )
    assert ok.status_code == 200
    # 改密后强制改密标志清除，新口令可登录
    assert client.get("/api/auth/me", headers=auth).json()["must_change_password"] == 0
    relogin = client.post("/api/auth/login", json={"emp_id": "00660301", "password": "Init@99999"})
    assert relogin.status_code == 200
    # 还原，保证用例可重复执行
    client.post(
        "/api/auth/change-password",
        json={"old_password": "Init@99999", "new_password": "Init@12345"},
        headers=auth,
    )


def test_bad_token_rejected(client):
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_workshop_setting_flow(client, auth):
    """所属车间：默认不限定 → 可设置 → 未知车间被拒 → 可清空还原。"""
    assert client.get("/api/auth/me", headers=auth).json()["workshop"] == ""

    r = client.post("/api/auth/workshop", json={"workshop": "一车间"}, headers=auth)
    assert r.status_code == 200 and r.json()["workshop"] == "一车间"
    assert client.get("/api/auth/me", headers=auth).json()["workshop"] == "一车间"

    bad = client.post("/api/auth/workshop", json={"workshop": "不存在的车间"}, headers=auth)
    assert bad.status_code == 400
    # 拒绝时不应改写已保存的值
    assert client.get("/api/auth/me", headers=auth).json()["workshop"] == "一车间"

    cleared = client.post("/api/auth/workshop", json={"workshop": ""}, headers=auth)
    assert cleared.status_code == 200 and cleared.json()["workshop"] == ""


def test_migrate_adds_workshop_to_legacy_db(tmp_path, monkeypatch):
    """旧库（users 表没有 workshop 列）启动后应被自动补列，历史行取空串。"""
    from sqlalchemy import create_engine

    from app import db as app_db

    eng = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE users (emp_id VARCHAR(32) PRIMARY KEY, name VARCHAR(64),"
            " password_hash VARCHAR(255), role VARCHAR(16), active INTEGER,"
            " must_change_password INTEGER, created_at VARCHAR(32))"
        )
        c.exec_driver_sql(
            "INSERT INTO users VALUES ('u1','旧用户','x','line',1,0,'2026-01-01 00:00:00')"
        )
        assert "workshop" not in {r[1] for r in c.exec_driver_sql("PRAGMA table_info(users)")}

    monkeypatch.setattr(app_db, "engine", eng)
    app_db.init_db()

    with eng.begin() as c:
        assert "workshop" in {r[1] for r in c.exec_driver_sql("PRAGMA table_info(users)")}
        assert c.exec_driver_sql("SELECT workshop FROM users WHERE emp_id='u1'").scalar() == ""
