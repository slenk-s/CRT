"""逐张替换照片：命名带版本号、旧文件保留、草稿原地覆盖、离线降级。

「追加」与「替换」的区别：
- 追加（POST /items/{id}/photo）：新增一张，seq 递增，卡片上多一个缩略图
- 替换（PUT /items/{id}/photos/{seq}）：换掉指定 seq 那张，照片数量不变，
  旧文件保留在共享盘上（版本历史要按 photo_rel_path 读回旧图）
"""
from app.services.storage import photo_display_name

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _co(client, auth, batch, date="2026-10-10"):
    return client.post("/api/changeover", json={"line": "1F01", "batch": batch, "shot_date": date},
                       headers=auth).json()


def _item(client, auth, cid, station):
    return client.post(f"/api/changeover/{cid}/items", json={"station": station},
                       headers=auth).json()


def _upload(client, auth, item_id, data=JPEG, name="a.jpg"):
    return client.post(f"/api/changeover/items/{item_id}/photo",
                       files={"file": (name, data, "image/jpeg")}, headers=auth)


def _replace(client, auth, item_id, seq, data=PNG, name="new.png"):
    return client.put(f"/api/changeover/items/{item_id}/photos/{seq}",
                      files={"file": (name, data, "image/jpeg")}, headers=auth)


def _submit(client, auth, cid):
    r = client.post(f"/api/changeover/{cid}/submit", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def _details(client, auth, cid):
    return {i["id"]: i for i in client.get(f"/api/changeover/{cid}", headers=auth).json()["items"]}


# ---------------------------------------------------------------- 已提交态替换


def test_replace_one_photo_keeps_count_and_old_file(client, fake_storage, auth):
    """已提交条目替换第 2 张：照片数量不变、旧文件留存、新名带 _v2、seq 1/3 不受影响。"""
    co = _co(client, auth, "R-1")
    it = _item(client, auth, co["id"], "白平衡工位")
    assert _upload(client, auth, it["id"], JPEG).status_code == 200
    assert _upload(client, auth, it["id"], PNG, name="b.png").status_code == 200
    assert _upload(client, auth, it["id"], JPEG, name="c.jpg").status_code == 200
    _submit(client, auth, co["id"])

    before = _details(client, auth, co["id"])[it["id"]]
    seq2_old_rel = [p for p in before["draft_photos"] if p["seq"] == 2][0]["rel_path"]
    seq1_rel = [p for p in before["draft_photos"] if p["seq"] == 1][0]["rel_path"]
    seq3_rel = [p for p in before["draft_photos"] if p["seq"] == 3][0]["rel_path"]

    r = _replace(client, auth, it["id"], 2, PNG, name="new.png")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_ver"] == 2

    photos = body["draft_photos"]
    # 替换不是追加：还是 3 张，seq 不变
    assert [p["seq"] for p in photos] == [1, 2, 3]
    p2 = photos[1]
    assert p2["seq"] == 2
    assert p2["name"] == photo_display_name("R-1", "白平衡工位", 2, "png", ver=2)
    assert p2["rel_path"].endswith(p2["name"])
    assert "_v2" in p2["rel_path"]
    assert p2["rel_path"] != seq2_old_rel
    # 其他两张纹丝不动
    assert photos[0]["rel_path"] == seq1_rel
    assert photos[2]["rel_path"] == seq3_rel
    # 旧文件仍在共享盘上——版本历史要读它
    assert seq2_old_rel in fake_storage.files
    assert fake_storage.files[p2["rel_path"]] == PNG
    # 按 seq 取图：第 2 张已是新图
    assert client.get(f"/api/changeover/items/{it['id']}/photos/2", headers=auth).content == PNG
    # 卡片「大小」是各图之和，不因替换而塌成单张
    assert body["draft_size"] == sum(len(x) for x in (JPEG, PNG, JPEG))


def test_replace_writes_new_version_and_keeps_history(client, fake_storage, auth):
    """替换生成 v2，edit_note 标为「替换照片 #2」，v1 仍指向最初的主图。"""
    co = _co(client, auth, "R-2")
    it = _item(client, auth, co["id"], "AV工位")
    _upload(client, auth, it["id"], JPEG)
    _upload(client, auth, it["id"], PNG, name="b.png")
    _submit(client, auth, co["id"])

    v1 = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()
    assert [v["ver"] for v in v1] == [1]
    v1_path = v1[0]["photo_rel_path"]

    _replace(client, auth, it["id"], 2, PNG, name="new.png")
    versions = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()
    assert [v["ver"] for v in versions] == [2, 1]
    assert versions[0]["edit_note"] == "替换照片 #2"
    assert versions[0]["photo_name"] == photo_display_name("R-2", "AV工位", 2, "png", ver=2)
    # v1 不受影响，仍指向最初的主图
    assert versions[1]["photo_rel_path"] == v1_path
    assert v1_path in fake_storage.files
    # 两个版本各自代理出各自的图
    assert client.get(f"/api/changeover/items/{it['id']}/photo?ver=1", headers=auth).content == JPEG
    assert client.get(f"/api/changeover/items/{it['id']}/photo?ver=2", headers=auth).content == PNG


def test_replace_missing_seq_404(client, fake_storage, auth):
    co = _co(client, auth, "R-3")
    it = _item(client, auth, co["id"], "耐压工位")
    _upload(client, auth, it["id"], JPEG)
    _submit(client, auth, co["id"])
    assert _replace(client, auth, it["id"], 99).status_code == 404


def test_submit_renames_all_photos_and_records_single_file_size(client, fake_storage, auth):
    """提交时每张草稿照片都补上 _v1；v1 版本记录的是单张大小（卡片总大小另行汇总）。"""
    co = _co(client, auth, "R-4")
    it = _item(client, auth, co["id"], "检P1工位")
    _upload(client, auth, it["id"], JPEG)
    _upload(client, auth, it["id"], PNG, name="b.png")
    _submit(client, auth, co["id"])

    detail = _details(client, auth, co["id"])[it["id"]]
    names = [p["name"] for p in detail["draft_photos"]]
    assert names == [
        photo_display_name("R-4", "检P1工位", 1, "jpg", ver=1),
        photo_display_name("R-4", "检P1工位", 2, "png", ver=1),
    ]
    # 草稿路径已不存在，正式路径两个都在
    assert not any("_draft" in k for k in fake_storage.files)
    for p in detail["draft_photos"]:
        assert p["rel_path"] in fake_storage.files
    v1 = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()[0]
    assert v1["file_size"] == len(JPEG)          # 单张，不是 2 张之和
    assert v1["photo_name"] == names[0]
    assert detail["draft_size"] == len(JPEG) + len(PNG)   # 卡片汇总


# ---------------------------------------------------------------- 草稿态替换


def test_replace_draft_photo_overwrites_in_place(client, fake_storage, auth):
    """草稿替换：原地覆盖同一路径，不产生版本。"""
    co = _co(client, auth, "R-5")
    it = _item(client, auth, co["id"], "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    _upload(client, auth, it["id"], PNG, name="b.png")
    before = client.get(f"/api/changeover/{co['id']}", headers=auth).json()["items"][0]
    rel2 = [p for p in before["draft_photos"] if p["seq"] == 2][0]["rel_path"]

    r = _replace(client, auth, it["id"], 2, PNG, name="new.png")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_ver"] == 0                 # 草稿没有版本
    assert [p["seq"] for p in body["draft_photos"]] == [1, 2]
    # 同名同路径，直接覆盖，草稿名不带版本号
    assert body["draft_photos"][1]["rel_path"] == rel2
    assert "_v" not in body["draft_photos"][1]["name"]
    assert fake_storage.files[rel2] == PNG
    assert client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json() == []


def test_replace_draft_photo_with_new_ext_cleans_old_file(client, fake_storage, auth):
    """草稿替换改了扩展名时，旧扩展名的文件要清掉，不留孤儿。"""
    co = _co(client, auth, "R-6")
    it = _item(client, auth, co["id"], "AV工位")
    _upload(client, auth, it["id"], JPEG)           # seq=1 → a.jpg
    before = client.get(f"/api/changeover/{co['id']}", headers=auth).json()["items"][0]
    old_rel = before["draft_photos"][0]["rel_path"]
    assert old_rel.endswith(".jpg") and old_rel in fake_storage.files

    r = _replace(client, auth, it["id"], 1, PNG, name="new.png")
    assert r.status_code == 200, r.text
    new_rel = r.json()["draft_photos"][0]["rel_path"]
    assert new_rel.endswith(".png")
    assert old_rel not in fake_storage.files      # 旧扩展名文件已清
    assert old_rel in fake_storage.removed
    assert fake_storage.files[new_rel] == PNG


# ---------------------------------------------------------------- 离线替换


def test_replace_offline_stages_locally_then_syncs(client, auth, offline_storage, monkeypatch):
    """SMB 离线时替换已提交条目：成功、落本地 synced=0、代理读本地，恢复后补推。"""
    from app.routers import changeover as router
    from app.services import sync as sync_svc
    from fakes import FakeStorage

    fake = FakeStorage()
    saved = router._test_smb_storage
    router._test_smb_storage = fake          # 阶段 1：在线创建 + 提交
    try:
        co = _co(client, auth, "R-7")
        it = _item(client, auth, co["id"], "耐压工位")
        _upload(client, auth, it["id"], JPEG)
        _submit(client, auth, co["id"])
        online_rel = client.get(f"/api/changeover/{co['id']}",
                                headers=auth).json()["items"][0]["draft_photos"][0]["rel_path"]
    finally:
        router._test_smb_storage = saved     # 阶段 2：离线替换

    r = _replace(client, auth, it["id"], 1, PNG, name="new.png")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_ver"] == 2
    assert body["has_photo_pending_sync"] is True
    p = body["draft_photos"][0]
    assert p["synced"] == 0
    assert "_v2" in p["rel_path"]
    local_rel = p["rel_path"]
    assert offline_storage["local"].exists(local_rel)
    # 离线照片仍可通过代理读到（走本地）
    assert client.get(p["url"], headers=auth).content == PNG
    # 在线时那份旧文件没被动过
    assert online_rel in fake.files

    # 模拟 SMB 恢复：探测线程写回 ok=True，后台同步按原 rel_path 推送
    recovered = FakeStorage()
    monkeypatch.setattr(sync_svc, "SmbStorage", lambda: recovered)
    assert sync_svc.smb_status(force=True)["ok"] is True
    sync_svc._sync_once()

    assert recovered.exists(local_rel)
    assert recovered.read_bytes(local_rel) == PNG
    assert not offline_storage["local"].exists(local_rel)
    p2 = client.get(f"/api/changeover/{co['id']}",
                    headers=auth).json()["items"][0]["draft_photos"][0]
    assert p2["synced"] == 1


# ---------------------------------------------------------------- 版本图代理


def test_version_photo_proxy_does_not_stall_on_dead_smb(client, auth, offline_storage, monkeypatch):
    """已判定离线时，版本图代理直接读本地，不去连 SMB。

    否则每张历史版本图都要白等一次连接超时（实测 5018ms）才回退到本地，
    离线翻版本历史会肉眼可见地卡住。
    """
    import app.services.sync as sync_svc
    from app.routers import changeover as co

    # 全程离线造一条已提交记录：照片落本地，提交时在本地搬运
    row = _co(client, auth, "R-8")
    it = _item(client, auth, row["id"], "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    _submit(client, auth, row["id"])

    class _NoConnect:
        def __init__(self):
            raise AssertionError("已判定离线时不应尝试连接 SMB")

    monkeypatch.setattr(co, "_test_smb_storage", None)
    monkeypatch.setattr(co, "SmbStorage", _NoConnect)
    monkeypatch.setattr(sync_svc, "smb_status",
                        lambda force=False: {"ok": False, "message": "SMB 不可用（离线）",
                                             "checked_at": "2026-10-14 02:00:00"})

    r = client.get(f"/api/changeover/items/{it['id']}/photo?ver=1", headers=auth)
    assert r.status_code == 200, r.text
    assert r.content == JPEG


def test_version_photo_proxy_still_probes_smb_before_first_check(client, auth, offline_storage,
                                                                 monkeypatch):
    """尚未探测（checked_at 为空）时必须照常查 SMB。

    共享盘上的照片是真实存在的，启动后头几秒若直接当作离线只读本地，会把这些照片误报 404。
    """
    import app.services.sync as sync_svc
    from app.routers import changeover as co
    from fakes import FakeStorage

    row = _co(client, auth, "R-9")
    it = _item(client, auth, row["id"], "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    _submit(client, auth, row["id"])
    rel = client.get(f"/api/changeover/{row['id']}",
                     headers=auth).json()["items"][0]["draft_photos"][0]["rel_path"]

    # 本地那份删掉，只在"共享盘"上留一份
    offline_storage["local"].remove(rel)
    assert not offline_storage["local"].exists(rel)
    smb = FakeStorage()
    smb.files[rel] = JPEG

    monkeypatch.setattr(co, "_test_smb_storage", None)
    monkeypatch.setattr(co, "SmbStorage", lambda: smb)
    monkeypatch.setattr(sync_svc, "smb_status",
                        lambda force=False: {"ok": False, "message": "尚未检查", "checked_at": ""})

    r = client.get(f"/api/changeover/items/{it['id']}/photo?ver=1", headers=auth)
    assert r.status_code == 200, r.text
    assert r.content == JPEG
