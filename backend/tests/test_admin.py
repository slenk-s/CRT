"""阶段 3.4 测试：管理端字典 / 用户（仅 admin，字典删除为物理删除）。"""


def test_admin_requires_admin(client, auth, line_auth):
    # 未登录
    assert client.get("/api/admin/lines").status_code == 401
    # 普通角色 403
    assert client.get("/api/admin/lines", headers=line_auth).status_code == 403
    assert client.post("/api/admin/lines", json={"workshop": "九车间", "line": "9F09"},
                       headers=line_auth).status_code == 403
    assert client.get("/api/admin/users", headers=line_auth).status_code == 403
    assert client.get("/api/stats/changeover", headers=line_auth).status_code == 403


def test_line_crud_and_hard_delete(client, auth):
    # 新增
    r = client.post("/api/admin/lines", json={"workshop": "九车间", "line": "9F08"}, headers=auth)
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["active"] == 1 and row["line"] == "9F08"
    # 重复 → 409
    assert client.post("/api/admin/lines", json={"workshop": "九车间", "line": "9F08"},
                       headers=auth).status_code == 409
    # 改名冲突 409 / 成功
    assert client.put(f"/api/admin/lines/{row['id']}", json={"line": "1F01"},
                      headers=auth).status_code == 409
    assert client.put(f"/api/admin/lines/{row['id']}",
                      json={"line": "9F88", "workshop": "九车间A", "sort": 5},
                      headers=auth).status_code == 200
    # 删除
    assert client.delete(f"/api/admin/lines/{row['id']}", headers=auth).status_code == 200
    # 管理端列表不可见
    admin_lines = client.get("/api/admin/lines", headers=auth).json()
    assert not any(x["line"] == "9F88" for x in admin_lines)
    # 字典读取也不返回
    dict_lines = {x["line"] for x in client.get("/api/dict/lines", headers=auth).json()["items"]}
    assert "9F88" not in dict_lines
    # 再次创建同名成功
    r = client.post("/api/admin/lines", json={"workshop": "九车间", "line": "9F88"}, headers=auth)
    assert r.status_code == 201 and r.json()["active"] == 1
    client.delete(f"/api/admin/lines/{r.json()['id']}", headers=auth)


def test_line_import(client, auth):
    r = client.post("/api/admin/lines/import",
                    json={"text": "九车间,9F01\n九车间；9F02\n\n"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2
    # 重复导入：跳过
    r2 = client.post("/api/admin/lines/import", json={"text": "九车间,9F01"}, headers=auth)
    assert r2.json()["skipped"] == 1 and r2.json()["added"] == 0
    # 无法解析
    assert client.post("/api/admin/lines/import", json={"text": "只有一列"},
                       headers=auth).status_code == 400


def test_deleted_line_history_visible(client, auth):
    line = client.post("/api/admin/lines", json={"workshop": "九车间", "line": "9F07"},
                       headers=auth).json()
    co = client.post("/api/changeover",
                     json={"line": "9F07", "batch": "ADM-1", "shot_date": "2026-10-08"},
                     headers=auth).json()
    assert co["workshop"] == "九车间"
    # 删除线体
    client.delete(f"/api/admin/lines/{line['id']}", headers=auth)
    # 字典不再返回，但历史转产详情仍可见线体/车间
    assert "9F07" not in {x["line"] for x in client.get("/api/dict/lines", headers=auth).json()["items"]}
    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    assert detail["line"] == "9F07" and detail["workshop"] == "九车间"
    # 删除后不能再新建转产
    assert client.post("/api/changeover",
                       json={"line": "9F07", "batch": "ADM-2"}, headers=auth).status_code == 400


def test_station_crud(client, auth):
    r = client.post("/api/admin/stations", json={"station": "测试工位Z", "sort": 999}, headers=auth)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post("/api/admin/stations", json={"station": "测试工位Z"},
                       headers=auth).status_code == 409
    assert client.put(f"/api/admin/stations/{sid}", json={"station": "测试工位Z2"},
                      headers=auth).status_code == 200
    assert client.delete(f"/api/admin/stations/{sid}", headers=auth).status_code == 200
    assert "测试工位Z2" not in {x["station"] for x in client.get("/api/dict/stations", headers=auth).json()}


def test_check_item_crud(client, auth):
    # 为白平衡工位加一个检查项
    r = client.post("/api/admin/check-items",
                    json={"station": "白平衡工位", "item": "临时检查项X", "sort": 999}, headers=auth)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    # 同工位同名 → 409
    assert client.post("/api/admin/check-items",
                       json={"station": "白平衡工位", "item": "临时检查项X"},
                       headers=auth).status_code == 409
    # 不存在的工位 → 400
    assert client.post("/api/admin/check-items",
                       json={"station": "不存在工位", "item": "x"}, headers=auth).status_code == 400
    # 命中字典读取
    items = {x["item"] for x in client.get("/api/dict/check-items",
                                           params={"station": "白平衡工位"}, headers=auth).json()}
    assert "临时检查项X" in items
    # 检查项删除为物理删除
    assert client.delete(f"/api/admin/check-items/{cid}", headers=auth).status_code == 200
    items = {x["item"] for x in client.get("/api/dict/check-items",
                                           params={"station": "白平衡工位"}, headers=auth).json()}
    admin_items = {x["item"] for x in client.get("/api/admin/check-items",
                                                  params={"station": "白平衡工位"}, headers=auth).json()}
    assert "临时检查项X" not in items
    assert "临时检查项X" not in admin_items
    # 删除后同工位同名可再次创建
    r = client.post("/api/admin/check-items",
                    json={"station": "白平衡工位", "item": "临时检查项X", "sort": 998}, headers=auth)
    assert r.status_code == 201, r.text
    assert client.delete(f"/api/admin/check-items/{r.json()['id']}", headers=auth).status_code == 200


def test_user_management(client, auth):
    # 已存在的测试账号（conftest 创建）
    users = client.get("/api/admin/users", headers=auth).json()
    assert any(u["emp_id"] == "T90001" and u["role"] == "line" for u in users)
    # 重复工号
    assert client.post("/api/admin/users",
                       json={"emp_id": "T90001", "name": "x", "password": "Abc@12345"},
                       headers=auth).status_code == 409
    # 改角色 + 停用
    assert client.put("/api/admin/users/T90001", json={"role": "admin"}, headers=auth).status_code == 200
    assert client.put("/api/admin/users/T90001", json={"active": 0}, headers=auth).status_code == 200
    # 停用后不能登录
    assert client.post("/api/auth/login",
                       json={"emp_id": "T90001", "password": "Line@12345"}).status_code == 401
    client.put("/api/admin/users/T90001", json={"active": 1, "role": "line"}, headers=auth)
    # 重置口令 → 强制改密
    assert client.put("/api/admin/users/T90001", json={"password": "Newpwd@123"}, headers=auth).status_code == 200
    r = client.post("/api/auth/login", json={"emp_id": "T90001", "password": "Newpwd@123"})
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] == 1
    # 自保护：不能停用/降级自己
    assert client.put("/api/admin/users/00660301", json={"active": 0}, headers=auth).status_code == 400
    assert client.put("/api/admin/users/00660301", json={"role": "line"}, headers=auth).status_code == 400
    # 不存在
    assert client.put("/api/admin/users/NOPE", json={"active": 1}, headers=auth).status_code == 404