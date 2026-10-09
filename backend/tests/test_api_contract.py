"""前端契约测试（阶段 7）。

逐条复现前端实际发出的请求形状（路径 / 查询参数 / 表单字段 / 响应字段），
确保前后端契约不漂移。与业务测试互补：这里只关心「前端能不能跑通」。
"""
from __future__ import annotations

# 1×1 透明 PNG，用于照片上传链路
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c63000100000500010d0a2db4000000"
    "0049454e44ae426082"
)


def test_frontend_flow(client, auth, fake_storage):
    # ---- 1) 字典（录入页/新建页依赖）----
    assert client.get("/api/dict/lines", headers=auth).status_code == 200
    by_ws = client.get("/api/dict/lines", headers=auth).json()["by_workshop"]
    assert by_ws.get("一车间") == [f"1F0{i}" for i in range(1, 8)]

    stations = client.get("/api/dict/stations", headers=auth).json()
    assert [s["station"] for s in stations][:2] == ["DeMura工位", "耐压工位"]

    ci = client.get("/api/dict/check-items", headers=auth, params={"station": "白平衡工位"}).json()
    assert ci and ci[0]["station"] == "白平衡工位" and "光感" in [c["item"] for c in ci]

    # ---- 2) 列表筛选参数形状（列表页）----
    r = client.get(
        "/api/changeover",
        headers=auth,
        params={
            "status": "draft", "line": "1F01",
            "date_from": "2020-01-01", "date_to": "2999-12-31",
            "keyword": "契约", "mine": "true", "page": 1, "size": 20,
        },
    )
    assert r.status_code == 200
    assert set(r.json()) >= {"total", "page", "size", "items"}

    # ---- 3) 创建草稿（新建页）----
    r = client.post("/api/changeover", headers=auth, json={"line": "1F01", "batch": "CONTRACT-001"})
    assert r.status_code == 201, r.text
    co = r.json()
    cid = co["id"]
    assert co["workshop"] == "一车间" and co["status"] == "draft"
    # 唯一冲突 → 409（前端据此提示「已存在」）
    assert client.post(
        "/api/changeover", headers=auth, json={"line": "1F01", "batch": "CONTRACT-001"}
    ).status_code == 409

    # ---- 4) 条目 + 勾选（录入页，check_result 为 JSON 字符串）----
    it = client.post(f"/api/changeover/{cid}/items", headers=auth, json={"station": "白平衡工位"}).json()
    r = client.patch(
        f"/api/changeover/items/{it['id']}", headers=auth,
        json={"check_result": '{"光感": true, "蓝牙": true}', "remark": "契约测试"},
    )
    assert r.status_code == 200
    assert r.json()["draft_remark"] == "契约测试"
    # 非法 JSON → 400（前端不做校验，靠后端兜底）
    assert client.patch(
        f"/api/changeover/items/{it['id']}", headers=auth, json={"check_result": "not-json"}
    ).status_code == 400

    # ---- 5) 照片上传（multipart，字段名 file）----
    r = client.post(
        f"/api/changeover/items/{it['id']}/photo", headers=auth,
        files={"file": ("t.png", PNG, "image/png")},
    )
    assert r.status_code == 200 and r.json()["has_draft_photo"] is True
    photo_url = r.json()["photo_url"]
    assert photo_url == f"/api/changeover/items/{it['id']}/photo"

    # ---- 6) 图片代理（AuthImage 用 Blob 方式取图）----
    img = client.get(photo_url, headers=auth)
    assert img.status_code == 200 and img.content == PNG

    # ---- 7) 统一提交（录入页底部）----
    r = client.post(f"/api/changeover/{cid}/submit", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["versions_created"] == 1 and body["failures"] == []

    # ---- 8) 详情 + 版本历史（详情页）----
    d = client.get(f"/api/changeover/{cid}", headers=auth).json()
    assert d["status"] == "submitted"
    assert d["items"][0]["current_ver"] == 1
    assert d["items"][0]["photo_url"] == f"/api/changeover/items/{it['id']}/photo?ver=1"

    vers = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()
    assert len(vers) == 1 and vers[0]["ver"] == 1
    assert vers[0]["photo_url"].startswith(f"/api/changeover/items/{it['id']}/photo?ver=1")
    assert set(vers[0]) >= {"ver", "photo_url", "check_result", "remark", "edit_note", "created_at"}

    # ---- 9) 更正 → 新版本（PUT）----
    r = client.put(
        f"/api/changeover/items/{it['id']}", headers=auth,
        json={"check_result": '{"光感": true}', "remark": "复测通过", "edit_note": "白平衡复测"},
    )
    assert r.status_code == 200 and r.json()["current_ver"] == 2
    assert len(client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()) == 2

    # ---- 10) 替换照片（提交态 → 新版本）----
    r = client.post(
        f"/api/changeover/items/{it['id']}/photo", headers=auth,
        files={"file": ("t2.png", PNG, "image/png")},
    )
    assert r.status_code == 200 and r.json()["current_ver"] == 3

    # ---- 11) CSV 导出（UTF-8 BOM，Excel 直开）----
    csv = client.get("/api/changeover/export.csv", headers=auth, params={"line": "1F01"})
    assert csv.status_code == 200
    assert csv.content.startswith(b"\xef\xbb\xbf")
    assert "白平衡工位" in csv.content.decode("utf-8-sig")
    assert "attachment" in csv.headers["content-disposition"]

    # ---- 12) 统计（趋势图数据源，仅 admin）----
    s = client.get("/api/stats/changeover", headers=auth, params={"days": 7}).json()
    assert s["days"] == 7 and len(s["series"]) == 7
    assert {"date", "changeovers", "items"} <= set(s["series"][0])
    assert isinstance(s["by_line"], list) and {"line", "count"} <= set(s["by_line"][0])

    # ---- 13) WB 查询（前端把多关键字用逗号拼接）----
    w = client.get("/api/wb/query", headers=auth, params={"batch": "B1,B2"}).json()
    assert w["mode"] == "batch" and len(w["results"]) == 2
    assert all(x["ok"] for x in w["results"]) and w["results"][0]["fields"]["批次"] == "B1"

    w2 = client.get("/api/wb/query", headers=auth, params={"bom": "BM-1,ERR-9"}).json()
    assert [x["ok"] for x in w2["results"]] == [True, False]
    assert w2["results"][1]["error"]

    assert client.get("/api/wb/status", headers=auth).json()["available"] is True
    # batch / bom 互斥 → 400
    assert client.get("/api/wb/query", headers=auth, params={"batch": "B1", "bom": "BM-1"}).status_code == 400

    # ---- 14) 管理端（字典/用户管理页）----
    imp = client.post("/api/admin/lines/import", headers=auth, json={"text": "九车间,9F11\n九车间,9F12"})
    assert imp.status_code == 200 and imp.json()["added"] == 2
    assert client.get("/api/admin/lines", headers=auth).status_code == 200
    assert client.get("/api/admin/stations", headers=auth).status_code == 200
    assert client.get("/api/admin/check-items", headers=auth).status_code == 200
    users = client.get("/api/admin/users", headers=auth).json()
    assert any(u["emp_id"] == "00660301" for u in users)

    # 删除字典项
    line_id = [x for x in client.get("/api/admin/lines", headers=auth).json() if x["line"] == "9F11"][0]["id"]
    assert client.delete(f"/api/admin/lines/{line_id}", headers=auth).status_code == 200
    admin_lines = client.get("/api/admin/lines", headers=auth).json()
    assert not any(x["id"] == line_id for x in admin_lines)

    # ---- 15) 权限边界（前端菜单隐藏 + 路由守卫，后端必须同样拦截）----
    client.post(
        "/api/admin/users", headers=auth,
        json={"emp_id": "T97777", "name": "契约线体员", "password": "CaTest@12345", "role": "line"},
    )
    lr = client.post("/api/auth/login", json={"emp_id": "T97777", "password": "CaTest@12345"})
    assert lr.status_code == 200, lr.text
    line_auth = {"Authorization": f"Bearer {lr.json()['token']}"}
    assert client.get("/api/admin/lines", headers=line_auth).status_code == 403
    assert client.get("/api/stats/changeover", headers=line_auth).status_code == 403
    # 普通用户可正常使用业务接口
    assert client.get("/api/changeover", headers=line_auth).status_code == 200
    assert client.get("/api/wb/query", headers=line_auth, params={"batch": "B9"}).status_code == 200
    assert client.get("/api/changeover", headers={}).status_code == 401

    # ---- 16) 删除草稿（列表页「删除」）----
    c2 = client.post("/api/changeover", headers=auth, json={"line": "2F01", "batch": "CONTRACT-DEL"}).json()
    assert client.delete(f"/api/changeover/{c2['id']}", headers=auth).status_code == 200
    assert client.get(f"/api/changeover/{c2['id']}", headers=auth).status_code == 404
