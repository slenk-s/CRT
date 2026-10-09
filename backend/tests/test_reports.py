"""阶段 5 测试：CSV 导出 / 统计预留。"""

JPEG = b"\\xff\\xd8\\xff\\xe0" + b"\\x00" * 64


def test_stats_requires_admin(client, line_auth):
    assert client.get("/api/stats/changeover").status_code == 401
    assert client.get("/api/stats/changeover", headers=line_auth).status_code == 403


def test_stats_structure(client, auth):
    co = client.post("/api/changeover", json={"line": "1F01", "batch": "ST-1"}, headers=auth).json()
    client.post(f"/api/changeover/{co['id']}/items", json={"station": "白平衡工位"}, headers=auth)
    body = client.get("/api/stats/changeover", headers=auth).json()
    assert body["days"] == 14 and len(body["series"]) == 14
    import datetime as _dt
    today = _dt.date.today().isoformat()
    today_row = [s for s in body["series"] if s["date"] == today][0]
    assert today_row["changeovers"] >= 1 and today_row["items"] >= 1
    assert any(x["line"] == "1F01" for x in body["by_line"])
    # days 参数边界
    assert len(client.get("/api/stats/changeover", params={"days": 7}, headers=auth).json()["series"]) == 7


def test_export_csv_submitted(client, fake_storage, auth):
    co = client.post("/api/changeover",
                     json={"line": "1F01", "batch": "EXP-1", "shot_date": "2026-10-08"},
                     headers=auth).json()
    cid = co["id"]
    it = client.post(f"/api/changeover/{cid}/items", json={"station": "白平衡工位"}, headers=auth).json()
    client.patch(f"/api/changeover/items/{it['id']}",
                 json={"check_result": '{"光感": true}', "remark": "导出测试"}, headers=auth)
    client.post(f"/api/changeover/items/{it['id']}/photo",
                files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=auth)
    assert client.post(f"/api/changeover/{cid}/submit", headers=auth).json()["ok"] is True

    r = client.get("/api/changeover/export.csv", params={"keyword": "EXP-1"}, headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "filename*=UTF-8''" in r.headers.get("content-disposition", "")
    text = r.content.decode("utf-8-sig")
    assert text.startswith("日期,车间,线体,批次,工位,版本") or "日期" in text.splitlines()[0]
    body = text.splitlines()
    assert len(body) == 2  # 表头 + 1 条工位条目
    assert "白平衡工位" in body[1] and "v1" in body[1] and "导出测试" in body[1] and "1F01" in body[1]
    assert "2026-10-08" in body[1]


def test_export_csv_draft_row(client, fake_storage, auth):
    co = client.post("/api/changeover",
                     json={"line": "1F01", "batch": "EXP-D", "shot_date": "2026-10-06"},
                     headers=auth).json()
    client.post(f"/api/changeover/{co['id']}/items", json={"station": "耐压工位"}, headers=auth)
    r = client.get("/api/changeover/export.csv", params={"keyword": "EXP-D"}, headers=auth)
    text = r.content.decode("utf-8-sig")
    lines = text.splitlines()
    assert len(lines) == 2 and "草稿" in lines[1] and "耐压工位" in lines[1]


def test_export_csv_requires_auth(client):
    assert client.get("/api/changeover/export.csv").status_code == 401