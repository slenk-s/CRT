"""阶段 4 测试：统一提交 / 版本化纠错 / 正式图代理（内存假存储）。"""
from app.services.storage import StorageError

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _co(client, auth, batch, date="2026-10-09"):
    return client.post("/api/changeover", json={"line": "1F01", "batch": batch, "shot_date": date},
                       headers=auth).json()


def _item(client, auth, cid, station):
    return client.post(f"/api/changeover/{cid}/items", json={"station": station},
                       headers=auth).json()


def _upload(client, auth, item_id, data=JPEG, name="a.jpg"):
    return client.post(f"/api/changeover/items/{item_id}/photo",
                       files={"file": (name, data, "image/jpeg")}, headers=auth)


def test_submit_requires_auth(client):
    assert client.post("/api/changeover/1/submit").status_code == 401


def test_submit_promotes_drafts(client, fake_storage, auth):
    co = _co(client, auth, "S-1")
    cid = co["id"]
    it1 = _item(client, auth, cid, "白平衡工位")
    it2 = _item(client, auth, cid, "耐压工位")
    # it1：传图 + 勾选 + 备注；it2：仅勾选（无照片）
    _upload(client, auth, it1["id"], JPEG)
    client.patch(f"/api/changeover/items/{it1['id']}",
                 json={"check_result": '{"光感": true}', "remark": "首件"}, headers=auth)
    client.patch(f"/api/changeover/items/{it2['id']}",
                 json={"check_result": '{"2500V&3S（4MΩ&2S）": true}'}, headers=auth)

    r = client.post(f"/api/changeover/{cid}/submit", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["status"] == "submitted"
    assert body["versions_created"] == 2 and body["no_photo_items"] == 1
    assert body["failures"] == []
    assert body["submitted_at"]

    # 草稿区已清空，正式区出现 v1
    draft_key = fake_storage.draft_rel(cid, it1["id"], "jpg")
    assert draft_key not in fake_storage.files
    final_path = fake_storage.final_rel("2026-10-09", "1F01", "S-1", "白平衡工位",
                                        "120000", "00660301", 1, "jpg")
    assert final_path in fake_storage.files
    assert fake_storage.files[final_path] == JPEG
    # 详情校验
    conver = client.get(f"/api/changeover/{cid}", headers=auth).json()
    assert conver["status"] == "submitted" and conver["item_total"] == 2 and conver["item_with_photo"] == 1
    # 已提交条目：photo_url 带版本号；无照片条目 photo_url 为 None
    by_station = {i["station"]: i for i in conver["items"]}
    assert by_station["白平衡工位"]["photo_url"].endswith(f"/items/{it1['id']}/photo?ver=1")
    assert by_station["白平衡工位"]["current_ver"] == 1
    assert by_station["白平衡工位"]["draft_remark"] == "首件"
    assert by_station["耐压工位"]["has_draft_photo"] is False
    assert by_station["耐压工位"]["photo_url"] is None

    # 重复提交被拒
    assert client.post(f"/api/changeover/{cid}/submit", headers=auth).status_code == 409


def test_submit_reports_moved_file_and_missing(client, fake_storage, auth):
    co = _co(client, auth, "S-2")
    cid = co["id"]
    good = _item(client, auth, cid, "白平衡工位")
    bad = _item(client, auth, cid, "AV工位")
    _upload(client, auth, good["id"], JPEG)
    _upload(client, auth, bad["id"], PNG, name="b.png")
    # 模拟 bad 的草稿文件在共享盘上丢失
    fake_storage.files.pop(fake_storage.draft_rel(cid, bad["id"], "png"))

    r = client.post(f"/api/changeover/{cid}/submit", headers=auth)
    body = r.json()
    assert body["ok"] is True and body["versions_created"] == 1
    assert len(body["failures"]) == 1 and body["failures"][0]["item_id"] == bad["id"]
    assert "缺失" in body["failures"][0]["reason"]
    # good 已归档，bad 的正式版本路径为空
    assert any("_v1.jpg" in p and "白平衡工位" in p for p in fake_storage.files)
    detail = client.get(f"/api/changeover/{cid}", headers=auth).json()
    by_station = {i["station"]: i for i in detail["items"]}
    assert by_station["AV工位"]["has_draft_photo"] is False


def test_submit_all_failed_aborts(client, fake_storage, auth):
    co = _co(client, auth, "S-3")
    cid = co["id"]
    it = _item(client, auth, cid, "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    fake_storage.files.clear()  # 唯一草稿丢失
    r = client.post(f"/api/changeover/{cid}/submit", headers=auth)
    body = r.json()
    assert body["ok"] is False and body["status"] == "draft" and body["versions_created"] == 0
    assert len(body["failures"]) == 1
    # 会话仍为草稿，可重新上传后提交
    assert client.get(f"/api/changeover/{cid}", headers=auth).json()["status"] == "draft"


def test_submit_without_items_rejected(client, fake_storage, auth):
    co = _co(client, auth, "S-4")
    assert client.post(f"/api/changeover/{co['id']}/submit", headers=auth).status_code == 400


def test_correct_creates_new_version(client, fake_storage, auth):
    co = _co(client, auth, "S-5")
    cid = co["id"]
    it = _item(client, auth, cid, "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    client.patch(f"/api/changeover/items/{it['id']}",
                 json={"check_result": '{"光感": true}', "remark": "v1"}, headers=auth)
    client.post(f"/api/changeover/{cid}/submit", headers=auth)

    # 更正：改勾选 + 备注 + 更正说明
    r = client.put(f"/api/changeover/items/{it['id']}",
                   json={"check_result": '{"光感": false}', "remark": "v2", "edit_note": "光感复测"},
                   headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_ver"] == 2
    assert body["draft_remark"] == "v2"
    assert body["photo_url"].endswith("?ver=2")

    versions = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()
    assert [v["ver"] for v in versions] == [2, 1]
    assert versions[0]["edit_note"] == "光感复测" and versions[0]["remark"] == "v2"
    assert versions[1]["remark"] == "v1"
    # 两版共用同一张照片文件
    assert versions[0]["photo_rel_path"] == versions[1]["photo_rel_path"] != ""

    # 列表/详情显示最新版
    detail = client.get(f"/api/changeover/{cid}", headers=auth).json()
    assert detail["items"][0]["current_ver"] == 2

    # 非法 JSON
    assert client.put(f"/api/changeover/items/{it['id']}",
                      json={"check_result": "not-json"}, headers=auth).status_code == 400


def test_correct_rejected_on_draft(client, fake_storage, auth):
    co = _co(client, auth, "S-6")
    it = _item(client, auth, co["id"], "白平衡工位")
    r = client.put(f"/api/changeover/items/{it['id']}",
                   json={"remark": "x", "edit_note": "y"}, headers=auth)
    assert r.status_code == 409


def test_replace_photo_after_submit_adds_version(client, fake_storage, auth):
    co = _co(client, auth, "S-7")
    cid = co["id"]
    it = _item(client, auth, cid, "耐压工位")
    _upload(client, auth, it["id"], JPEG)
    client.post(f"/api/changeover/{cid}/submit", headers=auth)
    v1_path = fake_storage.final_rel("2026-10-09", "1F01", "S-7", "耐压工位", "120000", "00660301", 1, "jpg")
    assert v1_path in fake_storage.files

    r = _upload(client, auth, it["id"], PNG, name="new.png")
    assert r.status_code == 200
    assert r.json()["current_ver"] == 2
    # 旧版文件保留 + 新版本文件存在
    assert v1_path in fake_storage.files
    assert any("_v2.png" in p for p in fake_storage.files)
    versions = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()
    assert [v["ver"] for v in versions] == [2, 1]
    assert versions[0]["edit_note"] == "替换照片"


def test_photo_proxy_by_version(client, fake_storage, auth):
    co = _co(client, auth, "S-8")
    cid = co["id"]
    it = _item(client, auth, cid, "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    client.post(f"/api/changeover/{cid}/submit", headers=auth)

    img1 = client.get(f"/api/changeover/items/{it['id']}/photo", params={"ver": 1}, headers=auth)
    assert img1.status_code == 200 and img1.content == JPEG
    # 代理要求登录
    assert client.get(f"/api/changeover/items/{it['id']}/photo", params={"ver": 1}).status_code == 401
    # 不存在的版本
    assert client.get(f"/api/changeover/items/{it['id']}/photo", params={"ver": 99},
                      headers=auth).status_code == 404


def test_versions_requires_auth_and_missing_item(client, fake_storage, auth):
    assert client.get("/api/changeover/items/1/versions").status_code == 401
    assert client.get("/api/changeover/items/999999/versions", headers=auth).status_code == 404