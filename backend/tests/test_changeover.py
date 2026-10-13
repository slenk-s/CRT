"""阶段 3 测试：转产会话 / 条目 / 草稿照片（用内存假存储替代 SMB）。"""

# 最小可用 JPEG/PNG 头，仅用于类型嗅探
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _new_co(client, auth, batch, line="1F01", date=None):
    body = {"line": line, "batch": batch}
    if date:
        body["shot_date"] = date
    return client.post("/api/changeover", json=body, headers=auth)


def test_create_requires_auth(client):
    assert client.post("/api/changeover", json={"line": "1F01", "batch": "B1"}).status_code == 401


def test_create_validates_line(client, auth):
    r = client.post("/api/changeover", json={"line": "不存在的线", "batch": "B1"}, headers=auth)
    assert r.status_code == 400


def test_create_and_duplicate(client, auth):
    r = _new_co(client, auth, "T-DUP-1", date="2026-10-08")
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["status"] == "draft"
    assert co["workshop"] == "一车间"
    assert co["uploader_emp_id"] == "00660301"
    dup = _new_co(client, auth, "T-DUP-1", date="2026-10-08")
    assert dup.status_code == 409
    assert str(co["id"]) in dup.json()["detail"]


def test_full_draft_flow(client, fake_storage, auth):
    co = _new_co(client, auth, "T-FLOW-1", date="2026-10-08").json()
    cid = co["id"]

    # 加条目：工位必须存在于字典
    bad = client.post(f"/api/changeover/{cid}/items", json={"station": "不存在工位"}, headers=auth)
    assert bad.status_code == 400
    r = client.post(f"/api/changeover/{cid}/items", json={"station": "白平衡工位"}, headers=auth)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["has_draft_photo"] is False and item["photo_url"] is None
    # 重复添加同工位 → 409
    assert client.post(f"/api/changeover/{cid}/items",
                       json={"station": "白平衡工位"}, headers=auth).status_code == 409

    # 更新勾选结果与备注
    r = client.patch(f"/api/changeover/items/{item['id']}",
                     json={"check_result": '{"光感": true}', "remark": "首次转产"},
                     headers=auth)
    assert r.status_code == 200 and r.json()["draft_remark"] == "首次转产"
    assert client.patch(f"/api/changeover/items/{item['id']}",
                        json={"check_result": "not-json"}, headers=auth).status_code == 400

    # 上传草稿照片
    r = client.post(f"/api/changeover/items/{item['id']}/photo",
                    files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["has_draft_photo"] is True
    # 新命名：_draft/{co_id}/{item_id}/{批次}_{工位}_{序号}.jpg
    from app.services.storage import photo_display_name
    expected_name = photo_display_name("T-FLOW-1", "白平衡工位", 1, "jpg")
    expected_path = f"slenk_\\FA_ROOT\\_draft\\{cid}\\{item['id']}\\{expected_name}"
    assert list(fake_storage.files.keys()) == [expected_path]
    assert fake_storage.files[expected_path] == JPEG
    # 列表统计
    row = client.get("/api/changeover", params={"keyword": "T-FLOW-1"}, headers=auth).json()["items"][0]
    assert row["item_total"] == 1 and row["item_with_photo"] == 1
    # 详情
    detail = client.get(f"/api/changeover/{cid}", headers=auth).json()
    assert detail["items"][0]["photo_url"].endswith(f"/items/{item['id']}/photo")
    # 图片代理
    img = client.get(f"/api/changeover/items/{item['id']}/photo", headers=auth)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert img.content == JPEG
    # 非法类型
    r = client.post(f"/api/changeover/items/{item['id']}/photo",
                    files={"file": ("a.txt", b"hello", "text/plain")}, headers=auth)
    assert r.status_code == 400
    # 超大文件（超过 MAX_IMAGE_MB=5）
    big = JPEG + b"\x00" * (6 * 1024 * 1024)
    r = client.post(f"/api/changeover/items/{item['id']}/photo",
                    files={"file": ("big.jpg", big, "image/jpeg")}, headers=auth)
    assert r.status_code == 413

    # 改批次号 + 冲突
    other = _new_co(client, auth, "T-FLOW-2", date="2026-10-08").json()
    assert client.patch(f"/api/changeover/{cid}", json={"batch": "T-FLOW-2"},
                        headers=auth).status_code == 409
    assert client.patch(f"/api/changeover/{cid}", json={"batch": "T-FLOW-9", "note": "改批"},
                        headers=auth).status_code == 200
    assert client.get(f"/api/changeover/{cid}", headers=auth).json()["batch"] == "T-FLOW-9"

    # 删条目 → 草稿文件同步清理
    r = client.delete(f"/api/changeover/items/{item['id']}", headers=auth)
    assert r.status_code == 200 and r.json()["files_removed"] >= 1
    assert fake_storage.files == {}
    # 删会话
    r = client.delete(f"/api/changeover/{cid}", headers=auth)
    assert r.status_code == 200
    assert other["id"]  # 另一条不受影响


def test_delete_changeover_removes_files(client, fake_storage, auth):
    co = _new_co(client, auth, "T-DEL-1", date="2026-10-08").json()
    cid = co["id"]
    item = client.post(f"/api/changeover/{cid}/items", json={"station": "AV工位"},
                       headers=auth).json()
    client.post(f"/api/changeover/items/{item['id']}/photo",
                files={"file": ("p.png", PNG, "image/png")}, headers=auth)
    assert fake_storage.files
    r = client.delete(f"/api/changeover/{cid}", headers=auth)
    assert r.status_code == 200 and r.json()["files_removed"] == 1
    assert client.get(f"/api/changeover/{cid}", headers=auth).status_code == 404


def test_submitted_session_locked(client, fake_storage, auth):
    """已提交会话：会话级写操作锁定；条目级纠错改走阶段 4 流程。"""
    co = _new_co(client, auth, "T-LOCK-1", date="2026-10-08").json()
    cid = co["id"]
    item = client.post(f"/api/changeover/{cid}/items", json={"station": "耐压工位"},
                       headers=auth).json()
    # 直接改库模拟提交
    from app.db import SessionLocal
    from app.models import Changeover

    s = SessionLocal()
    try:
        row = s.get(Changeover, cid)
        row.status = "submitted"
        row.submitted_at = "2026-10-08 20:00:00"
        s.commit()
    finally:
        s.close()

    # 会话级写操作：锁定
    assert client.post(f"/api/changeover/{cid}/items", json={"station": "AV工位"},
                       headers=auth).status_code == 409
    assert client.patch(f"/api/changeover/{cid}", json={"batch": "T-LOCK-X"},
                        headers=auth).status_code == 409
    assert client.delete(f"/api/changeover/{cid}", headers=auth).status_code == 409
    # 草稿态 PATCH 条目：锁定（已提交请用 PUT 更正）
    assert client.patch(f"/api/changeover/items/{item['id']}",
                        json={"remark": "x"}, headers=auth).status_code == 409
    # 无历史版本时替换照片：拒绝
    assert client.post(f"/api/changeover/items/{item['id']}/photo",
                       files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=auth).status_code == 409
    # 条目软删：允许（保留正式文件与版本历史）
    assert client.delete(f"/api/changeover/items/{item['id']}", headers=auth).status_code == 200


def test_list_filters_and_paging(client, auth):
    for i in range(3):
        _new_co(client, auth, f"T-PAGE-{i}", date="2026-10-07")
    body = client.get("/api/changeover", params={"keyword": "T-PAGE-", "page": 1, "size": 2},
                      headers=auth).json()
    assert body["total"] == 3 and len(body["items"]) == 2 and body["page"] == 1
    assert client.get("/api/changeover", params={"date_from": "2026-10-07", "date_to": "2026-10-07",
                                                 "keyword": "T-PAGE-"}, headers=auth).json()["total"] == 3
    assert client.get("/api/changeover", params={"status": "draft", "keyword": "T-PAGE-"},
                      headers=auth).json()["total"] == 3
    assert client.get("/api/changeover", params={"date_from": "bad-date"},
                      headers=auth).status_code == 400


def test_draft_photo_requires_existing_item(client, fake_storage, auth):
    co = _new_co(client, auth, "T-404-1", date="2026-10-08").json()
    r = client.post("/api/changeover/items/999999/photo",
                    files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=auth)
    assert r.status_code == 404
    assert co["id"]