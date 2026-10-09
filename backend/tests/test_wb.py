"""阶段 6 测试：WB 参数查询（mock 数据源，不连内网）。"""
import app.config as cfg


def test_wb_requires_auth(client):
    assert client.get("/api/wb/query", params={"batch": "B1"}).status_code == 401
    assert client.get("/api/wb/status").status_code == 401


def test_wb_query_by_batch_ok(client, auth):
    r = client.get("/api/wb/query", params={"batch": "B20261008A"}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "batch" and body["source"] == "MockSource"
    assert len(body["results"]) == 1
    res = body["results"][0]
    assert res["ok"] is True and res["key"] == "B20261008A"
    # 字段原样透传、且**保持顺序**（首键为「批次」）
    assert list(res["fields"].keys())[0] == "批次"
    assert res["fields"]["批次"] == "B20261008A"
    assert set(["BOM", "产品平台", "色坐标", "Gamma"]).issubset(res["fields"])


def test_wb_query_by_bom_ok(client, auth):
    body = client.get("/api/wb/query", params={"bom": "BM-001"}, headers=auth).json()
    assert body["mode"] == "bom" and body["results"][0]["ok"] is True
    assert body["results"][0]["fields"]["BOM"] == "BM-001"


def test_wb_query_multi_batch_single_failure(client, auth):
    body = client.get("/api/wb/query", params={"batch": "OK-1,ERR-2\nOK-3"}, headers=auth).json()
    keys = [r["key"] for r in body["results"]]
    assert keys == ["OK-1", "ERR-2", "OK-3"]
    flags = {r["key"]: r["ok"] for r in body["results"]}
    assert flags == {"OK-1": True, "ERR-2": False, "OK-3": True}
    failed = [r for r in body["results"] if not r["ok"]][0]
    assert "模拟失败" in failed["error"] and failed["fields"] == {}


def test_wb_query_param_validation(client, auth):
    # 两者都缺 / 都给 → 400
    assert client.get("/api/wb/query", headers=auth).status_code == 400
    assert client.get("/api/wb/query", params={"batch": "B", "bom": "M"}, headers=auth).status_code == 400
    # 只有分隔符 → 400
    assert client.get("/api/wb/query", params={"batch": ", ,"}, headers=auth).status_code == 400


def test_wb_status_available(client, auth):
    body = client.get("/api/wb/status", headers=auth).json()
    assert body["available"] is True and body["source"] == "MockSource"


def test_wb_unavailable_returns_503(client, auth, monkeypatch):
    monkeypatch.setattr(cfg, "WB_SOURCE", "off")
    assert client.get("/api/wb/query", params={"batch": "B1"}, headers=auth).status_code == 503
    st = client.get("/api/wb/status", headers=auth).json()
    assert st["available"] is False and st["source"] is None