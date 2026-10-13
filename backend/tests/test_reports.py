"""阶段 5 测试：CSV 导出 / 统计预留。"""
import csv as _csv
import io as _io

JPEG = b"\\xff\\xd8\\xff\\xe0" + b"\\x00" * 64

HEADER = ["日期", "车间", "线体", "批次", "工位", "状态", "版本", "检查项", "备注",
          "照片数", "文件名", "上传人工号", "上传人", "提交时间"]


def _rows(text):
    """CSV 文本 → (表头索引, 数据行列表)。用 csv 解析，避免靠字符串拼接断言。"""
    rows = list(_csv.reader(_io.StringIO(text)))
    return {h: i for i, h in enumerate(rows[0])}, rows[1:]


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
    """已提交行：状态/版本分列、勾选结果展平、多图合并、无内部路径、有提交时间。"""
    co = client.post("/api/changeover",
                     json={"line": "1F01", "batch": "EXP-1", "shot_date": "2026-10-08"},
                     headers=auth).json()
    cid = co["id"]
    it = client.post(f"/api/changeover/{cid}/items", json={"station": "白平衡工位"}, headers=auth).json()
    client.patch(f"/api/changeover/items/{it['id']}",
                 json={"check_result": '{"光感": true, "白平衡": false}', "remark": "导出测试"},
                 headers=auth)
    for name in ("a.jpg", "b.jpg"):
        client.post(f"/api/changeover/items/{it['id']}/photo",
                    files={"file": (name, JPEG, "image/jpeg")}, headers=auth)
    assert client.post(f"/api/changeover/{cid}/submit", headers=auth).json()["ok"] is True

    r = client.get("/api/changeover/export.csv", params={"keyword": "EXP-1"}, headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "filename*=UTF-8''" in r.headers.get("content-disposition", "")
    text = r.content.decode("utf-8-sig")
    idx, rows = _rows(text)
    assert list(idx) == HEADER
    assert len(rows) == 1          # 一个工位一行
    row = rows[0]
    assert row[idx["日期"]] == "2026-10-08"
    assert row[idx["线体"]] == "1F01"
    assert row[idx["工位"]] == "白平衡工位"
    assert row[idx["状态"]] == "已提交"
    assert row[idx["版本"]] == "v1"
    assert row[idx["备注"]] == "导出测试"
    # 勾选结果展平为已勾选项，不写裸 JSON
    assert row[idx["检查项"]] == "光感"
    # 多张照片合并到一格（按 seq 升序、分号分隔），并给出张数
    assert row[idx["照片数"]] == "2"
    assert row[idx["文件名"]] == "EXP-1_白平衡工位_1_v1.jpg; EXP-1_白平衡工位_2_v1.jpg"
    # 不再带共享盘内部路径
    assert not any("slenk_" in c or "\\" in c for c in row)
    # 提交时间来自会话提交时刻，非空
    assert row[idx["提交时间"]]


def test_export_csv_draft_row(client, fake_storage, auth):
    """草稿行：状态=草稿、版本留空、无提交时间；照片信息不能再是空的。"""
    co = client.post("/api/changeover",
                     json={"line": "1F01", "batch": "EXP-D", "shot_date": "2026-10-06"},
                     headers=auth).json()
    it = client.post(f"/api/changeover/{co['id']}/items",
                     json={"station": "耐压工位"}, headers=auth).json()
    client.post(f"/api/changeover/items/{it['id']}/photo",
                files={"file": ("a.jpg", JPEG, "image/jpeg")}, headers=auth)

    r = client.get("/api/changeover/export.csv", params={"keyword": "EXP-D"}, headers=auth)
    idx, rows = _rows(r.content.decode("utf-8-sig"))
    assert len(rows) == 1
    row = rows[0]
    assert row[idx["工位"]] == "耐压工位"
    assert row[idx["状态"]] == "草稿"
    assert row[idx["版本"]] == ""
    assert row[idx["提交时间"]] == ""
    # 回归：草稿行的文件名/张数原来永远是空的（读的是从未写过的 CoItem.draft_name）
    assert row[idx["照片数"]] == "1"
    assert row[idx["文件名"]] == "EXP-D_耐压工位_1.jpg"


def test_export_csv_requires_auth(client):
    assert client.get("/api/changeover/export.csv").status_code == 401


def test_export_csv_groups_by_batch_with_blank_line(client, fake_storage, auth):
    """按批次号排序分组，批次之间留一个空行（CSV 上不了色，用留白代替色阶）。"""
    # 故意乱序创建，确认导出后同批次聚在一起、批次号升序
    for batch in ("GRP-B", "GRP-A2", "GRP-A1"):
        co = client.post("/api/changeover",
                         json={"line": "1F01", "batch": batch, "shot_date": "2026-10-07"},
                         headers=auth).json()
        for station in ("白平衡工位", "AV工位"):
            client.post(f"/api/changeover/{co['id']}/items",
                        json={"station": station}, headers=auth)

    r = client.get("/api/changeover/export.csv", params={"keyword": "GRP-"}, headers=auth)
    body = list(_csv.reader(_io.StringIO(r.content.decode("utf-8-sig"))))[1:]

    batches, blanks = [], 0
    for row in body:
        if not row:
            blanks += 1
            continue
        batches.append(row[3])       # 批次列
    assert batches == ["GRP-A1", "GRP-A1", "GRP-A2", "GRP-A2", "GRP-B", "GRP-B"]
    assert blanks == 2               # 3 个批次 → 组间 2 个空行（末尾不留）