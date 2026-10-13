"""SMB 离线降级测试：验证上传/读取/删除/提交在 SMB 不可用时的行为。

覆盖点：
- 草稿态上传 → 落本地临时目录，synced=0，前端可看到 pending_sync
- 离线态照片代理仍可访问（走本地）
- 离线态提交 → 草稿照片在本地移到正式目录，synced 保持 0，会话直接转正
- 后台同步服务：SMB 恢复后按原相对路径推送，离线时不动文件与记录
- 单张照片/会话删除 → 清本地文件
- 多图连续上传 → 全部落本地
- 提交态追加照片：SMB 离线时拒绝（503），不写新版本
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


# ---------------------------------------------------------------- 上传


def test_upload_offline_writes_to_local(client, auth, offline_storage):
    """SMB 离线：草稿照片写本地，synced=0，前端显示待同步。"""
    co = _co(client, auth, "OFF-1")
    it = _item(client, auth, co["id"], "白平衡工位")
    r = _upload(client, auth, it["id"], JPEG)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_draft_photo"] is True
    assert body["has_photo_pending_sync"] is True
    p = body["draft_photos"][0]
    assert p["synced"] == 0
    assert p["seq"] == 1
    # 文件名统一命名
    assert p["name"] == photo_display_name("OFF-1", "白平衡工位", 1, "jpg")
    # 本地目录里真的有文件，路径结构与 SMB 的相对路径一致
    assert offline_storage["local"].exists(p["rel_path"])
    assert offline_storage["local"].read_bytes(p["rel_path"]) == JPEG
    # SMB 假对象收到 write 调用但都抛错了
    assert "write_bytes" in str(offline_storage["smb"].calls) or len(offline_storage["smb"].calls) >= 1


def test_upload_multiple_offline(client, auth, offline_storage):
    """离线可连续上传多张照片，全部落本地、seq 递增。"""
    co = _co(client, auth, "OFF-2")
    it = _item(client, auth, co["id"], "耐压工位")
    r1 = _upload(client, auth, it["id"], JPEG, name="a.jpg")
    r2 = _upload(client, auth, it["id"], PNG, name="b.png")
    assert r1.status_code == 200 and r2.status_code == 200
    photos = r2.json()["draft_photos"]
    assert [p["seq"] for p in photos] == [1, 2]
    assert all(p["synced"] == 0 for p in photos)
    assert r2.json()["has_photo_pending_sync"] is True
    # 本地两个文件都在
    for p in photos:
        assert offline_storage["local"].exists(p["rel_path"])


# ---------------------------------------------------------------- 读取


def test_photo_proxy_offline_reads_from_local(client, auth, offline_storage):
    """离线时照片代理接口仍能从本地读出原字节。"""
    co = _co(client, auth, "OFF-3")
    it = _item(client, auth, co["id"], "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    # 按 seq 代理
    r = client.get(f"/api/changeover/items/{it['id']}/photos/1", headers=auth)
    assert r.status_code == 200, r.text
    assert r.content == JPEG
    assert r.headers["content-type"].startswith("image/jpeg")
    # 旧版兼容代理
    r2 = client.get(f"/api/changeover/items/{it['id']}/photo", headers=auth)
    assert r2.status_code == 200 and r2.content == JPEG


# ---------------------------------------------------------------- 删除


def test_delete_single_photo_offline(client, auth, offline_storage):
    """离线时删除草稿单张照片：清本地文件 + 删 DB 记录。"""
    co = _co(client, auth, "OFF-4")
    it = _item(client, auth, co["id"], "白平衡工位")
    r = _upload(client, auth, it["id"], JPEG)
    photo = r.json()["draft_photos"][0]
    rel = photo["rel_path"]
    assert offline_storage["local"].exists(rel)
    r = client.delete(f"/api/changeover/items/{it['id']}/photos/{photo['seq']}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] is True
    assert not offline_storage["local"].exists(rel)
    # 详情页不再有照片
    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    assert detail["items"][0]["draft_photos"] == []


def test_delete_session_offline_cleans_local(client, auth, offline_storage):
    """离线时删除整个草稿会话：清本地草稿照片 + 删条目与会话。"""
    co = _co(client, auth, "OFF-5")
    it1 = _item(client, auth, co["id"], "白平衡工位")
    it2 = _item(client, auth, co["id"], "AV工位")
    _upload(client, auth, it1["id"], JPEG)
    _upload(client, auth, it1["id"], PNG, name="b.png")
    _upload(client, auth, it2["id"], JPEG)
    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    rels = [p["rel_path"] for it in detail["items"] for p in it["draft_photos"]]
    assert len(rels) == 3
    for rel in rels:
        assert offline_storage["local"].exists(rel)
    r = client.delete(f"/api/changeover/{co['id']}", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["files_removed"] == 3
    for rel in rels:
        assert not offline_storage["local"].exists(rel)
    # 会话消失
    assert client.get(f"/api/changeover/{co['id']}", headers=auth).status_code == 404


# ---------------------------------------------------------------- 提交


def test_submit_offline_moves_local_keeps_pending(client, auth, offline_storage):
    """离线提交：草稿照片仅在本地移到正式目录，synced 保持 0，会话直接转正。"""
    co = _co(client, auth, "OFF-6")
    it1 = _item(client, auth, co["id"], "白平衡工位")
    it2 = _item(client, auth, co["id"], "耐压工位")
    _upload(client, auth, it1["id"], JPEG)
    _upload(client, auth, it2["id"], JPEG)
    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    draft_rels = [p["rel_path"] for i in detail["items"] for p in i["draft_photos"]]
    assert len(draft_rels) == 2
    for rel in draft_rels:
        assert "_draft" in rel.replace("/", "\\")
        assert offline_storage["local"].exists(rel)

    r = client.post(f"/api/changeover/{co['id']}/submit", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "submitted"
    assert body["versions_created"] == 2
    assert body["no_photo_items"] == 0
    assert body["failures"] == []

    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    assert detail["status"] == "submitted"
    by_id = {i["id"]: i for i in detail["items"]}
    for it in (it1, it2):
        item_out = by_id[it["id"]]
        assert item_out["current_ver"] == 1
        assert item_out["has_photo_pending_sync"] is True
        assert len(item_out["draft_photos"]) == 1
        p = item_out["draft_photos"][0]
        # synced 保持 0，等 SMB 恢复后由后台同步推送
        assert p["synced"] == 0
        # 相对路径已从 _draft 区改为正式归档区
        assert "_draft" not in p["rel_path"].replace("/", "\\")
        assert offline_storage["local"].exists(p["rel_path"])
    # 原草稿文件是被"移动"而非复制残留
    for rel in draft_rels:
        assert not offline_storage["local"].exists(rel)
    # 版本记录指向正式区路径
    v1 = client.get(f"/api/changeover/items/{it1['id']}/versions", headers=auth).json()
    assert len(v1) == 1
    assert "_draft" not in v1[0]["photo_rel_path"].replace("/", "\\")


def test_submit_offline_partial_no_photo_item(client, auth, offline_storage):
    """离线提交（部分条目无照片）：全部条目生成 v1，离线照片保持待同步。"""
    co = _co(client, auth, "OFF-7")
    it1 = _item(client, auth, co["id"], "白平衡工位")  # 有照片
    it2 = _item(client, auth, co["id"], "AV工位")      # 无照片
    _upload(client, auth, it1["id"], JPEG)

    r = client.post(f"/api/changeover/{co['id']}/submit", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "submitted"
    assert body["versions_created"] == 2
    assert body["no_photo_items"] == 1
    assert body["failures"] == []
    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    assert detail["status"] == "submitted"
    by_station = {i["station"]: i for i in detail["items"]}
    assert by_station["AV工位"]["current_ver"] == 1
    assert by_station["AV工位"]["photo_url"] is None
    assert by_station["白平衡工位"]["current_ver"] == 1
    p = by_station["白平衡工位"]["draft_photos"][0]
    assert p["synced"] == 0
    assert by_station["白平衡工位"]["has_photo_pending_sync"] is True


def test_sync_service_pushes_pending_after_recovery(client, auth, offline_storage, monkeypatch):
    """离线提交留下的 synced=0 照片，SMB 恢复后由后台同步按原路径推送到共享盘。"""
    from app.services import sync as sync_svc
    from fakes import FakeStorage

    co = _co(client, auth, "OFF-10")
    it = _item(client, auth, co["id"], "耐压工位")
    _upload(client, auth, it["id"], JPEG)
    assert client.post(f"/api/changeover/{co['id']}/submit", headers=auth).json()["ok"] is True

    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    p = detail["items"][0]["draft_photos"][0]
    assert p["synced"] == 0
    rel_final = p["rel_path"]
    assert offline_storage["local"].exists(rel_final)

    # 模拟 SMB 恢复：后台同步改走可用的内存存储
    smb = FakeStorage()
    monkeypatch.setattr(sync_svc, "SmbStorage", lambda: smb)
    # 探测线程会先发现恢复并写回 ok=True，同步才继续；这里显式走一次同样的流程，
    # 免得用例依赖全局状态缓存里残留的判定结果。
    assert sync_svc.smb_status(force=True)["ok"] is True
    sync_svc._sync_once()

    assert smb.exists(rel_final)
    assert smb.read_bytes(rel_final) == JPEG
    assert not offline_storage["local"].exists(rel_final)
    p2 = client.get(f"/api/changeover/{co['id']}", headers=auth).json()["items"][0]["draft_photos"][0]
    assert p2["synced"] == 1


def test_sync_service_skips_when_smb_offline(client, auth, offline_storage):
    """SMB 仍离线时，同步服务一轮不同步任何文件，也不改动记录。"""
    from app.services import sync as sync_svc

    co = _co(client, auth, "OFF-11")
    it = _item(client, auth, co["id"], "白平衡工位")
    _upload(client, auth, it["id"], JPEG)
    assert client.post(f"/api/changeover/{co['id']}/submit", headers=auth).json()["ok"] is True
    p = client.get(f"/api/changeover/{co['id']}", headers=auth).json()["items"][0]["draft_photos"][0]

    n = sync_svc._sync_once()
    assert n == 0
    assert offline_storage["local"].exists(p["rel_path"])
    p2 = client.get(f"/api/changeover/{co['id']}", headers=auth).json()["items"][0]["draft_photos"][0]
    assert p2["synced"] == 0


# ---------------------------------------------------------------- 已提交态追加


def test_submit_mixed_photos_offline_fails_whole_item(client, auth, offline_storage):
    """同一条目里既有共享盘照片（synced=1）又有本地照片（synced=0），SMB 离线时整条失败。

    synced=1 的照片只存在于共享盘上，本地没有副本，离线时无法归档；
    此时不能让同条目其他照片「一半转正、一半留在草稿」。
    """
    from app.routers import changeover as router
    from fakes import FakeStorage

    fake = FakeStorage()
    saved = router._test_smb_storage
    router._test_smb_storage = fake  # 阶段 1：SMB 在线，照片进共享盘
    try:
        co = _co(client, auth, "OFF-9")
        it = _item(client, auth, co["id"], "白平衡工位")
        assert _upload(client, auth, it["id"], JPEG).status_code == 200
    finally:
        router._test_smb_storage = saved  # 阶段 2：SMB 离线，追加照片落本地

    r = _upload(client, auth, it["id"], PNG, name="b.png")
    assert r.status_code == 200, r.text
    photos = r.json()["draft_photos"]
    assert [p["synced"] for p in photos] == [1, 0]
    local_rel = photos[1]["rel_path"]
    smb_rel = photos[0]["rel_path"]
    assert offline_storage["local"].exists(local_rel)

    r = client.post(f"/api/changeover/{co['id']}/submit", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "draft"
    assert body["versions_created"] == 0
    assert len(body["failures"]) == 1
    assert "SMB" in body["failures"][0]["reason"]

    # 本地照片仍在草稿区原处，没有被搬进正式区
    detail = client.get(f"/api/changeover/{co['id']}", headers=auth).json()
    assert detail["status"] == "draft"
    item = detail["items"][0]
    assert item["current_ver"] == 0
    assert [p["rel_path"] for p in item["draft_photos"]] == [smb_rel, local_rel]
    assert offline_storage["local"].exists(local_rel)
    assert "_draft" in local_rel.replace("/", "\\")
    assert client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json() == []


def test_append_photo_offline_succeeds_pending(client, auth, offline_storage):
    """已提交条目在 SMB 离线时追加照片：照常成功，落本地 synced=0，等后台补推。

    分两阶段：先用 FakeStorage 走一遍创建+提交（模拟 SMB 在线），再切到离线态追加。

    回归点：早年这里直接返回 503，但文件其实已经写进本地目录、记录却没建，
    等于留下一个永远同步不到的孤儿文件（后台同步只认数据库记录）。
    """
    from app.routers import changeover as router
    from fakes import FakeStorage

    fake = FakeStorage()
    saved = router._test_smb_storage
    router._test_smb_storage = fake
    try:
        co = _co(client, auth, "OFF-8")
        it = _item(client, auth, co["id"], "耐压工位")
        assert _upload(client, auth, it["id"], JPEG).status_code == 200
        assert client.post(f"/api/changeover/{co['id']}/submit", headers=auth).json()["ok"] is True
    finally:
        router._test_smb_storage = saved

    # 阶段 2：SMB 离线（offline_storage fixture 已置 BrokenSmb），追加照片
    r = _upload(client, auth, it["id"], PNG, name="new.png")
    assert r.status_code == 200, r.text
    assert r.json()["current_ver"] == 2
    assert r.json()["has_photo_pending_sync"] is True
    # 新版本已建，新照片落本地待同步
    versions = client.get(f"/api/changeover/items/{it['id']}/versions", headers=auth).json()
    assert [v["ver"] for v in versions] == [2, 1]
    assert versions[0]["edit_note"] == "追加照片"
    new_photo = [p for p in r.json()["draft_photos"] if p["seq"] == 2][0]
    assert new_photo["synced"] == 0
    assert offline_storage["local"].exists(new_photo["rel_path"])
    # 离线照片走本地代理仍可读
    assert client.get(new_photo["url"], headers=auth).content == PNG
    # 旧版文件仍在共享盘上，未被触碰
    assert fake.files


# ---------------------------------------------------------------- 健康检查接口


def test_health_reports_smb_status_and_pending(client, auth, offline_storage):
    """/api/health 报告实时 SMB 连通性与待同步照片数量。"""
    co = _co(client, auth, "OFF-12")
    it = _item(client, auth, co["id"], "白平衡工位")
    _upload(client, auth, it["id"], JPEG)

    # 生产环境由后台探测线程刷新缓存，这里手动触发一次
    from app.services import sync as sync_svc
    assert sync_svc.smb_status(force=True)["ok"] is False

    r = client.get("/api/health", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "storage" in body and isinstance(body["storage"], dict)
    smb = body["smb"]
    assert isinstance(smb, dict)
    assert smb["ok"] is False
    assert smb["message"]
    assert smb["checked_at"]
    assert isinstance(body["pending_sync"], int)
    assert body["pending_sync"] >= 1


def test_smb_status_probe(monkeypatch):
    """smb_status()：已配置但不可达 → ok=False；可达 → ok=True。"""
    from app.services import sync as sync_svc
    from fakes import BrokenSmbStorage

    monkeypatch.setattr(sync_svc.config, "SMB_HOST", "10.0.0.1")
    monkeypatch.setattr(sync_svc.config, "SMB_SHARE", "pub")
    monkeypatch.setattr(sync_svc, "SmbStorage", lambda: BrokenSmbStorage())
    st = sync_svc.smb_status(force=True)
    assert st["ok"] is False
    assert "SMB" in st["message"]

    class _OkSmb:
        def reachable(self):
            return True

    monkeypatch.setattr(sync_svc, "SmbStorage", lambda: _OkSmb())
    st = sync_svc.smb_status(force=True)
    assert st["ok"] is True
    assert st["checked_at"]

    # 非 force 只读缓存，绝不发起探测（否则 /api/health 会被网络超时拖慢）
    def _no_probe():
        raise AssertionError("不应在读取状态时探测 SMB")

    monkeypatch.setattr(sync_svc, "SmbStorage", lambda: _no_probe())
    assert sync_svc.smb_status()["ok"] is True

    # 未配置时明确报告未配置，而不是含糊的"离线"
    monkeypatch.setattr(sync_svc.config, "SMB_HOST", "")
    st = sync_svc.smb_status(force=True)
    assert st["ok"] is False
    assert "未配置" in st["message"]


def test_write_photo_fallback_treats_unknown_status_as_offline(monkeypatch, tmp_path):
    """状态还停在「检测中」（尚未探测）时按离线处理：不尝试连 SMB，直接落本地。

    否则每次上传都要先白等一次连接超时（约 5s），界面看着像卡住。
    """
    import app.services.sync as sync_svc
    from app.routers import changeover as co
    from app.services.storage import LocalStorage

    class _NoConnect:
        def __init__(self):
            raise AssertionError("状态未定时不应尝试连接 SMB")

    monkeypatch.setattr(co, "_test_smb_storage", None)
    monkeypatch.setattr(co, "_test_local_storage", LocalStorage(str(tmp_path)))
    monkeypatch.setattr(co, "SmbStorage", _NoConnect)
    monkeypatch.setattr(sync_svc, "smb_status",
                        lambda force=False: {"ok": False, "message": "尚未检查", "checked_at": ""})

    rel = r"slenk_\FA_ROOT\a\b.png"
    synced, actual = co._write_photo_fallback(rel, b"PNGDATA")
    assert synced == 0 and actual == rel
    assert (tmp_path / "slenk_" / "FA_ROOT" / "a" / "b.png").read_bytes() == b"PNGDATA"


def test_write_photo_fallback_uses_smb_when_probe_says_online(monkeypatch, tmp_path):
    """探测判定在线时正常写 SMB（synced=1）。"""
    import app.services.sync as sync_svc
    from app.routers import changeover as co
    from app.services.storage import LocalStorage
    from fakes import FakeStorage

    fake = FakeStorage()
    monkeypatch.setattr(co, "_test_smb_storage", None)
    monkeypatch.setattr(co, "_test_local_storage", LocalStorage(str(tmp_path)))
    monkeypatch.setattr(co, "SmbStorage", lambda: fake)
    monkeypatch.setattr(sync_svc, "smb_status",
                        lambda force=False: {"ok": True, "message": "", "checked_at": "2026-10-13 05:00:00"})

    synced, rel = co._write_photo_fallback(r"slenk_\FA_ROOT\a\b.png", b"DATA")
    assert synced == 1
    assert fake.files[rel] == b"DATA"
