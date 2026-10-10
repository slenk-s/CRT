"""wb_mail v6 自持取数层：批次 → BOM → 白平衡/MID/ODF/料单 → 有序参数字典。

设计约束：
- **包内不含任何端点或密钥明文**，端点由 mes_env 在运行时从 T盘注入；
- 仅标准库 + requests（料单鉴权走公共 token-proxy，保底 TCL_BUSINESS_TOKEN）；
- 输出与历史版本保持同一字段口径与顺序，邮件层无需感知取数来源变化。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from wb_mail import config as C
from wb_mail import mes_env

log = C.log

MID_ORG_ID = 90002082
BOM_ENDPOINT = "/tpwo/v1/pwo/prod-batch-boms"
BOM_PAGE_SIZE = 1000          # 实测 2000 会超时
BOM_MAX_ROWS = 4000
PLATFORM_SEGMENT = 1          # strBomdesc 以 '/' 分段，取第 2 段为产品平台


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
def clean_batch(batch: str) -> str:
    """批次清洗：先按 '.' 取首段，再按 '-' 取首段。"""
    b = str(batch or "").strip()
    if "." in b:
        b = b.split(".")[0]
    if "-" in b:
        b = b.split("-")[0]
    return b


def _post(url: str, payload: Any, timeout: int,
          headers: Optional[dict] = None, tries: int = 3) -> dict:
    """POST JSON。实测 MES 网关在并发下偶发返回截断响应，故单次调用内重试，
    避免退化到上层整条链路重跑。
    """
    data = json.dumps(payload).encode("utf-8")
    last: Optional[Exception] = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json", **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (json.JSONDecodeError, urllib.error.URLError, OSError) as e:
            last = e
            if i < tries - 1:
                time.sleep(0.6 * (i + 1))
        except Exception:
            raise                      # 业务级错误（Success=false 等）不重试
    raise RuntimeError("接口响应异常(%s): %s" % (type(last).__name__, str(last)[:120]))


def _num(v: Any) -> str:
    s = str(v).strip()
    try:
        return "%g" % float(s)
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# 各数据源
# ---------------------------------------------------------------------------
def fetch_bom_by_batch(batch: str, timeout: int = 10) -> str:
    """按批次取 MID，从里面解析 BomNum。"""
    url = mes_env.get("MID_API_URL")
    if not url:
        raise RuntimeError("MID_API_URL 未注入，无法由批次解析 BOM")
    payload = {
        "ApiType": "MIDInfoController",
        "Parameters": [{"Value": ""}, {"Value": batch}, {"Value": ""}],
        "Method": "GetMidInfo",
        "Context": {"InvOrgId": MID_ORG_ID},
    }
    resp = _post(url, payload, timeout)
    rows = (((resp.get("Result") or {}).get("Result")) or [])
    for r in rows:
        if str(r.get("strItem", "")).upper() in ("BOMNUM", "BOM_NUM", "BOM"):
            v = r.get("ItemValue")
            if v:
                return str(v).strip()
    for r in rows:
        if r.get("BomNum"):
            return str(r["BomNum"]).strip()
    return ""


def _decode_result(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value.strip())
    except json.JSONDecodeError:
        return None


def _detail_pair(row: Any) -> tuple[Any, Any] | None:
    if not isinstance(row, dict):
        return None
    name = row.get("StrProcName") or row.get("strItem")
    name = name or row.get("Name") or row.get("name")
    for key in ("StrProcValue", "ItemValue", "Value", "value"):
        if row.get(key) is not None:
            return name, row[key]
    return name, None


def _white_details(data: dict) -> dict[str, str]:
    """白平衡 Result 兼容解析：Result 常为 JSON 字符串 → details 列表。"""
    result = _decode_result(data.get("Result"))
    out: dict[str, str] = {}
    if isinstance(result, dict):
        for meta in ("strBom", "strBomdesc"):
            if result.get(meta) is not None:
                out[meta] = str(result[meta])
        details = result.get("details") or result.get("Details") or []
    else:
        details = result if isinstance(result, list) else []
    for row in details:
        pair = _detail_pair(row)
        if pair is None:
            continue
        name, val = pair
        if name is not None:
            out[str(name)] = val
    return out


def fetch_white(batch: str, bom: str, timeout: int = 10) -> dict[str, str]:
    url = mes_env.get("TIOT_URL")
    if not url:
        raise RuntimeError("TIOT_URL 未注入，无法查询白平衡")
    payload = {"method": "GetWhiteInfoByBomNum",
               "data": {"sn": "", "batch": batch, "bom": bom}}
    resp = _post(url, payload, timeout)
    data = resp.get("data") or {}
    if not data.get("Success"):
        raise RuntimeError("白平衡接口返回失败: %s" % str(resp)[:200])
    return _white_details(data)


def fetch_mid_by_bom(bom: str, timeout: int = 10) -> dict[str, str]:
    url = mes_env.get("TIOT_URL")
    payload = {"method": "GetMidInfoByBomNum", "data": bom}
    resp = _post(url, payload, timeout)
    data = resp.get("data") or {}
    out: dict[str, str] = {}
    for r in data.get("Result") or []:
        if isinstance(r, dict) and r.get("strItem") is not None:
            out[str(r["strItem"])] = r.get("ItemValue")
    return out


def fetch_odf(batch: str, timeout: int = 8) -> dict[str, str]:
    """ODF 订单配置：免鉴权，按批次取 Project/Value，多值合并。"""
    url = mes_env.get("ODF_URL")
    if not url:
        return {}
    try:
        resp = _post(url, {"batch": batch}, timeout)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("ODF 查询异常: %s", e)
        return {}
    if str(resp.get("code")) not in ("0",):
        log.warning("ODF 非成功返回 code=%s", resp.get("code"))
        return {}
    data_list = resp.get("data") or []
    if not isinstance(data_list, list) or not data_list:
        return {}
    return _aggregate_odf_items((data_list[0] or {}).get("Data") or [])


def _aggregate_odf_items(items: list) -> dict[str, str]:
    agg: dict[str, list[str]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        proj = it.get("Project") or it.get("project")
        val = it.get("Value") if it.get("Value") is not None else it.get("value")
        if not proj or val in (None, ""):
            continue
        agg.setdefault(str(proj).strip().lower(), []).append(str(val).strip())
    return {k: " / ".join(v) for k, v in agg.items()}


# ---------------------------------------------------------------------------
# 料单（侧标样式 + 无线模组/WiFi6/蓝牙判定共用一次拉取）
# ---------------------------------------------------------------------------
TP_SCRIPTS = os.environ.get("TOKEN_PROXY_SCRIPTS",
                            "/mnt/skills/public/token-proxy/token-proxy/scripts")
def _load_auth_session():
    try:
        if TP_SCRIPTS not in sys.path:
            sys.path.insert(0, TP_SCRIPTS)
        from token_helper import auth_session
    except Exception as e:
        return None, e
    return auth_session, None


def _session_auth_parts(session) -> tuple[list[str], list[str]]:
    try:
        import requests
        default_keys = {key.lower() for key in requests.Session().headers}
    except ImportError:
        default_keys = set()
    extra = [key for key in session.headers if key.lower() not in default_keys]
    cookies = [cookie.name for cookie in session.cookies]
    return extra, cookies


def _tp_session():
    """公共 token-proxy 换票：401 自动刷新，与业务代码解耦。"""
    token_names = ("TCL_TOKEN", "DEERFLOW_USER_TOKEN", "TCL_BUSINESS_TOKEN")
    if not any(os.environ.get(name) for name in token_names):
        return None, "无平台初始令牌"
    auth_session, error = _load_auth_session()
    if error:
        return None, "token-proxy 不可用(%s)" % type(error).__name__

    cfg_path = mes_env.ensure_token_config()
    if not cfg_path:
        return None, "MES_DOMAIN 未注入或换票配置生成失败"
    skill_dir = os.path.dirname(os.path.dirname(cfg_path))
    try:
        s = auth_session(domain=mes_env.get("MES_DOMAIN"), skill_dir=skill_dir)
    except Exception as e:
        return None, "换票异常(%s:%s)" % (type(e).__name__, str(e)[:80])
    if s is None:
        return None, "换票返回空 Session"

    # 鉴权头键名由换票接口动态返回，不能假定是 Authorization。
    extra, cookies = _session_auth_parts(s)
    if not extra and not cookies:
        return None, "换票未注入鉴权头/cookie"
    log.info("料单换票成功，注入头: %s cookie: %s", extra or "-", cookies or "-")
    return s, "token-proxy"


def _bom_session():
    """构造已鉴权 Session：公共 token-proxy 优先，保底平台令牌。"""
    s, why = _tp_session()
    base_headers = {
        "Referer": mes_env.get("MES_REFERER"),
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/146.0.0.0 Safari/537.36"),
        "lotToken": "null",
        "Accept": "application/json, text/plain, */*",
    }
    if s is not None:
        for k, v in base_headers.items():
            s.headers.setdefault(k, v)
        return s

    tk = (os_environ_get("MES_TOKEN") or os_environ_get("TCL_BUSINESS_TOKEN")
          or os_environ_get("TCL_TOKEN"))
    if not tk:
        raise RuntimeError("料单鉴权不可用（%s；且无 MES_TOKEN/TCL_BUSINESS_TOKEN）" % why)
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("未安装 requests，无法查询料单") from e
    t = str(tk).strip()
    if t.lower().startswith("bearer "):
        t = t[7:]
    s = requests.Session()
    s.headers.update(base_headers)
    s.headers.update({"Authorization": "Bearer " + t})
    log.info("料单使用保底令牌（token-proxy 原因: %s）", why)
    return s


def os_environ_get(k: str) -> str:
    import os
    return (os.environ.get(k) or "").strip()


def fetch_bom_rows(batch: str, timeout: int = 45, retries: int = 2) -> list[dict]:
    """分页拉取批次料单行。失败返回 []（上层降级，不阻断发信）。"""
    base = mes_env.get("MES_API_BASE")
    if not base:
        log.warning("MES_API_BASE 未注入，跳过料单（侧标样式将为空）")
        return []
    try:
        sess = _bom_session()
    except RuntimeError as e:
        log.warning("料单鉴权失败: %s", e)
        return []

    rows: list[dict] = []
    page = 0
    while len(rows) < BOM_MAX_ROWS:
        payload = _fetch_bom_page(sess, base, batch, page, timeout, retries)
        if payload is None:
            break
        content = _extract_content(payload)
        if not content:
            break
        rows.extend(content)
        total = payload.get("totalElements") if isinstance(payload, dict) else None
        page += 1
        if total and len(rows) >= int(total):
            break
        if len(content) < BOM_PAGE_SIZE:
            break
    return rows


def _extract_content(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for k in ("content", "data", "list", "records", "rows"):
        v = payload.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            for kk in ("content", "list", "records", "rows"):
                if isinstance(v.get(kk), list):
                    return v[kk]
    return []


def _fetch_bom_page(session, base: str, batch: str, page: int,
                    timeout: int, retries: int) -> Optional[dict]:
    """读取一页料单；仅对网络异常和服务端错误做有限重试。"""
    for attempt in range(retries + 1):
        try:
            response = session.get(
                base + BOM_ENDPOINT,
                params={"page": page, "size": BOM_PAGE_SIZE, "wbsNo": batch},
                timeout=timeout,
            )
            if response.status_code == 200:
                return response.json()
            log.warning("料单 HTTP %d page=%d", response.status_code, page)
            if response.status_code < 500:
                return None
        except Exception as exc:
            log.warning("料单请求异常 page=%d attempt=%d: %s",
                        page, attempt + 1, str(exc)[:120])
        if attempt < retries:
            time.sleep(min(2 ** attempt, 4))
    return None


_SKIP_SEGS = ("冲压", "下前框", "上前框", "前框", "面壳", "后壳", "整机", "模组",
              "其它", "其他", "黑色", "白色", "银色", "侧标", "铭牌", "标牌", "LOGO",
              "装饰片", "无斜纹", "Tesa", "限用物质标准", "斜纹")


_GENERIC_RES = (re.compile(r"^[A-Z]{1,4}$"),                   # AL / DEC 短码
                re.compile(r"^[A-Z][0-9]+[A-Z0-9-]*$"),        # M005 / A04407-0 / H0901-000226
                re.compile(r"^[A-Z]{2,3}[0-9][A-Z0-9]{6,}$"),  # TK1N2983020ED4 机型码
                re.compile(r"=", re.I), re.compile(r"[0-9] ?mm", re.I))


def _generic_seg(seg: str) -> bool:
    """判断某段是否为"分类/规格填充段"（不是样式名）。注意统一大写比较，
    否则列表里的 Tesa 与段里的 TESA 永不相等（上一版就是这么把样式名漏成 Tesa 6304 的）。"""
    u = seg.upper()
    if any(k.upper() in u for k in _SKIP_SEGS) or len(seg) > 40:
        return True
    return any(rx.fullmatch(u) or rx.search(seg) for rx in _GENERIC_RES)


def side_label_from_material(maktx: str) -> Optional[str]:
    """从侧标物料描述提取 LOGO 样式名。

    料单两种真实结构（都以标记段为起点**正向**取第一个非泛化段即可通吃）：
      A `75TK1N2侧标(1) 冲压LOGO Premium QD-MiniLED 其它 黑色M005 ... Tesa 6304 ... H0901-000278`
      B `98TK1N2侧标(0) 冲压LOGO 其它 其它 M005 TK1N2983020ED4 ... H0901-000226 Premium SQD-MiniLED`
    结构 B 里样式名在末段，是因为它前面全是填充段；所以**不能**从末段倒扫——
    倒扫会先撞上 Tesa 6304 / 简体中文 这类尾段（上一版实测把 A 类也改坏了）。
    无 LOGO 且无 侧标 标记段的物料（如 铭牌类贴纸\\主铭牌\\...）一律不提取。
    """
    segs = [x.strip() for x in str(maktx or "").replace("/", chr(92)).split(chr(92)) if x.strip()]
    idx = next((i for i, sg in enumerate(segs) if "LOGO" in sg.upper()), None)
    if idx is None:
        idx = next((i for i, sg in enumerate(segs) if "侧标" in sg), None)
    if idx is None:
        return None
    for cand in segs[idx + 1:]:
        if not _generic_seg(cand):
            return cand
    return None


def side_label_from_rows(rows: list) -> str:
    """侧标物料优先（maktx 含"侧标"）；铭牌/标牌类仅作次级兜底，
    且必须带 LOGO 标记段，否则 主铭牌/后铭牌 之类会吐出"简体中文"等垃圾值。"""
    alt = ""
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        maktx = str(r.get("maktx", "") or "")
        if "侧标" in maktx:
            v = side_label_from_material(maktx)
            if v:
                return v
        elif not alt and ("铭牌" in maktx or "标牌" in maktx) and "LOGO" in maktx.upper():
            v = side_label_from_material(maktx)
            if v:
                alt = v
    return alt


def fetch_side_label(batch: str) -> str:
    return side_label_from_rows(fetch_bom_rows(batch))


# ---------------------------------------------------------------------------
# 无线模组 / WiFi6 / 蓝牙判定（移植自 whitebalance-batch-info 的 mes_bom）
# 为什么不用白平衡接口字段：WiFi6 socket detection 在多数 BOM 上为空，
# 判不出"有/无"。料单里的模组芯片型号才是可靠依据，接口字段仅作兜底。
# ---------------------------------------------------------------------------
_WIFI_SUBSTR = ("无线", "wlan", "wi-fi", "wifi")
_BT_SUBSTR = ("蓝牙", "bluetooth")

# 料单里蓝牙写作独立段 "BT"（如 `...,WIFI,BT\98JX`）。绝不能把 "BT" 当子串匹配：
# 同一张料单里 MMBT3904(三极管)、ISBTL2024091001(连接器)、高色域BT2020 都含 "BT"，
# 子串匹配会把它们全判成带蓝牙。故按分隔符切段后做整段/版本号匹配。
_BT_SEG = re.compile(r"^(?:BT|BT\d+(?:\.\d+)*|蓝牙|BLUETOOTH(?:\d+(?:\.\d+)*)?)$")
_SEG_SPLIT = re.compile(r"[\\/,;:()\[\]\s]+")


def _has_bt(hay: str) -> bool:
    if any(x in hay.lower() for x in _BT_SUBSTR):
        return True
    for seg in _SEG_SPLIT.split(str(hay).upper()):
        if seg and _BT_SEG.match(seg):
            return True
    return False


# WiFi6 / 6E / 7 (802.11ax/bt) 芯片关键前缀
_WIFI6_CHIPS = ('MT7921', 'MT7922', 'MT7925', 'MT7920', 'MT7664', 'MT7664H',
                'RTL8852', 'RTL8922', 'RTL8852BE', 'RTL8852AE', 'AW-AN545', 'AW-CB366',
                'AW-CB605', 'CYW555', 'IW611', 'BCM4389', 'QCN9074', 'SDX-WIFI6',
                # GSD 多合一小板：SWT6652* 支持 WiFi6（产线口径，人工确认）。
                # 注意与 SW6652* 区分——后者**只到 WiFi5**，登记在 _WIFI5_MAX_CHIPS。
                # 归一化只去 -/空格/_、不去字母 T，故 'SW6652' 匹配不到 'SWT6652AU'，
                # 反之亦然，两族不会互相误命中。
                'SWT6652')
# 仅 WiFi5 (802.11ac) 或更低 —— 用于判 WiFi6=无
# MT7663（料单串如 `MT7663BU`/`MT7663BUN`）：802.11ac(WiFi5)+BT 组合芯片，**不支持
# WiFi6**。原误登记在 _WIFI6_CHIPS，导致 GTO503801B(98M9LF，料单含 MT7663BU*) 被误判
# WiFi6=有；产线口径确认判"无"，故移入本表。
# RTL8731（料单串 `G0303-000200`，描述写 2.400-2.483/5.150-5.250/5.725-5.825GHz
# 双频、无 6GHz/ax 字样）：WiFi5 模组，32S5LR(如 GLD500354A/GLD500392A)用，判 WiFi6=无。
_WIFI5_MAX_CHIPS = ('RTL8822', 'RTL8821', 'RTL8192', 'RTL8188', 'RTL8731', 'MT7663', 'MT7668', 'MT7615',
                    'MT7603', 'MT7612', 'AP6255', 'AP6356', 'BCM4345', 'BCM43438',
                    'BCM4356', 'CYW43', 'CYW55570',
                    # GSD 多合一小板 SW6652*（料单串如 `SW6652-AU`，描述写
                    # 2.4GHz/5.8GHz/5GHz 双频、无 ax/6E 字样）：产线口径确认
                    # **不支持 WiFi6**，故判"无"而非"待确认"。
                    'SW6652')
# 纯 WiFi（不带蓝牙）芯片：只有命中这些才敢判 蓝牙=无
# RTL8731：料单 G0303-000200 只列 WiFi 频段、无 BT 字样，按审慎口径不判蓝牙=有。
_WIFI_ONLY_CHIPS = ('RTL8188', 'RTL8192', 'RTL8723', 'RTL8731', 'MT7603', 'MT7612', 'MT7610',
                    'BCM43438', 'BCM43430', 'AP6212', 'CYW43438', 'CYW43012', 'ESP32')
# 描述里出现即判 WiFi6=有 的显式文本信号（如 FFC 线写 WIFI6、802.11ax）
_WIFI6_TEXT = ('wifi6', 'wifi-6', 'wifi 6', 'wi-fi6', 'wi-fi 6', 'wifi6e',
               '802.11ax', '80211ax', '6ghz', '三频')


def _chips_in(text: str, table) -> list:
    tt = str(text).upper().replace("-", "").replace(" ", "").replace("_", "")
    return [c for c in table
            if c.upper().replace("-", "").replace(" ", "").replace("_", "") in tt]


def _contains_any(text: str, candidates) -> bool:
    return any(candidate in text for candidate in candidates)


def _is_wireless_module(description: str, upper: str) -> bool:
    if _contains_any(description, ("多合一小板", "无线模组", "WiFi模组")):
        return True
    return "WIFI" in upper and _contains_any(description, ("组件", "模组"))


def _wireless_row(row: Any) -> Optional[dict[str, Any]]:
    """提取单条料单中的无线信号；无关行返回 None。"""
    if not isinstance(row, dict):
        return None
    matnr = str(row.get("matnr", "") or "")
    maktx = str(row.get("maktx", "") or "")
    hay = maktx + " " + matnr
    low = hay.lower()
    upper = maktx.upper()
    chip6 = _chips_in(hay, _WIFI6_CHIPS)
    chip5 = _chips_in(hay, _WIFI5_MAX_CHIPS)
    has_chip = bool(chip6 or chip5)
    wifi_token = _contains_any(low, _WIFI_SUBSTR)
    bluetooth_token = _has_bt(hay)
    is_module = _is_wireless_module(maktx, upper)
    if not (wifi_token or bluetooth_token or has_chip or is_module):
        return None
    return {
        # 双证据交叉：芯片 与（显式文案/模组标记）分开上报，待批次级合并后再判
        # WiFi 有无，单一信号不再直接判「有」。
        "chip": has_chip,
        "text": wifi_token or is_module,
        "bt": bluetooth_token or (
            has_chip and not _chips_in(hay, _WIFI_ONLY_CHIPS)
        ),
        "wifi6": True if chip6 else False if chip5 else None,
        "explicit6": _contains_any(low, _WIFI6_TEXT),
        "chipset": max(chip6 or chip5, key=len) if has_chip else "",
        "material": "%s %s" % (matnr, maktx[:80]),
    }


def detect_wireless_rows(rows: list) -> dict:
    """扫描料单行，返回 {wifi, bt, wifi6, chipset, material, chip_evidence, text_evidence}。

    第二层校验（双证据交叉）：WiFi 有无需「芯片」与「显式文案/模组标记」两类独立
    证据同时成立才判 wifi=True；只命中一类时 wifi=False，但 chip_evidence /
    text_evidence 置位，供调用方判「待确认」而非「无」。

    wifi6 三态：True=有 / False=无 / None=待确认（有无线模组但芯片与文本都无法定代际）。
    """
    has_bt = False
    chip_ev = text_ev = False
    wifi6 = None
    chipset = ""
    material = ""
    explicit6 = False

    for row in rows or []:
        signal = _wireless_row(row)
        if signal is None:
            continue
        chip_ev = chip_ev or signal["chip"]
        text_ev = text_ev or signal["text"]
        has_bt = has_bt or signal["bt"]
        explicit6 = explicit6 or signal["explicit6"]
        if signal["wifi6"] is True:
            wifi6 = True
        elif signal["wifi6"] is False and wifi6 is not True:
            wifi6 = False
        if signal["chipset"] and not chipset:
            chipset = signal["chipset"]
            material = signal["material"]
        elif not material:
            material = signal["material"]

    if explicit6:
        wifi6 = True
    return {"wifi": chip_ev and text_ev, "bt": has_bt, "wifi6": wifi6,
            "chipset": chipset, "material": material,
            "chip_evidence": chip_ev, "text_evidence": text_ev}


# ---------------------------------------------------------------------------
# 字段口径（名称与顺序即邮件契约）
# ---------------------------------------------------------------------------
_COORD_MODES = ("Normal", "Warm", "Warm2", "Cool")

_WHITE_SPECS: list[tuple[str, str, str, dict]] = [
    # (中文名, 接口键, 变换, 映射表)
    *[((m + " 色坐标" + ax), "HDMI_%s_Color_Coordinate_%s" % (m, ax.lower()), "coord", {})
      for m in _COORD_MODES for ax in ("X", "Y")],
    ("白平衡 R 上限", "Limit_Max_R_GAIN", "num", {}),
    ("白平衡 G 上限", "Limit_Max_G_GAIN", "num", {}),
    ("白平衡 B 上限", "Limit_Max_B_GAIN", "num", {}),
    ("目标 Gamma", "Gamma_Target", "num", {}),
    ("Gamma 容差", "Gamma_Range", "num", {}),
    ("调试方式", "Align_mode", "map", {"0": "白平衡", "1": "Gamma"}),
    ("最大亮度", "Maximum_luminance_min", "num", {}),
    ("串口", "Serial_port", "str", {}),
    ("窗口白场值", "Window_white_value", "num", {}),
    ("白平衡对齐方式", "WB_Aligment_Mode", "str", {}),
    ("测量仪器", "Measuring_Instrument", "str", {}),
    ("面板类型", "Panel_Type", "str", {}),
    ("功放数量", "Audio_Amp_Num", "num", {}),
    ("光感", "Light_Sensor_Func", "bool", {}),
    ("远场语音", "FFS_Func", "bool", {}),
    ("局部调光", "Local_Dimming_Func", "bool_inv", {}),
    ("DeMura", "DeMura_Align", "map",
     {"0": "不调(0)", "1": "TCONLESS(1&黑白)", "2": "TCON(2&黑白)",
      "6": "克洛斯(6&彩色)", "7": "背光(7&彩色)"}),
    ("WIFI6模块", "WiFi6 socket detection", "bool", {}),
    ("cusMACwrite", "ClaroMacWr", "bool", {}),
]

_MID_SPECS = [
    ("机型名", "Model_Name"), ("PID/项目号", "PROJECTID"),
    ("DeviceID", "DeviceID"), ("MAC 规则", "MAC"),
]

# KEY/证书类：接口里存在该键才输出
_KEY_SPECS = [
    ("HDCP-KEY", "HDCP-KEY"), ("HDCP2.2-KEY", "HDCP2.2-KEY"),
    ("HDCP2.3-KEY", "HDCP2.3-KEY"), ("Multiple-HDCP-KEY", "Multiple-HDCP-KEY"),
    ("MGK-KEY", "MGK-KEY"), ("Widevine-KEY", "Widevine-KEY"),
    ("ECP-KEY", "ECP-KEY"), ("PlayReady-KEY", "PlayReady-key"),
    ("Attestation-KEY", "Attestation-key"), ("CI-PLUS-KEY", "CI-PLUS-KEY"),
    ("NETFLIX-ESN", "NETFILX-ESN"), ("WST-KEY", "WST-KEY"),
    ("Tlicense-KEY", "Tlicense-key"), ("Fairplay-KEY", "Fairplay-KEY"),
    ("PEK", "PEK"), ("DAK", "DAK"), ("YouTubeKey", "YouTubeKey"),
    ("MS12Key", "MS12Key"), ("FVPKey", "FVPKey"),
]

# (中文名, [ODF project 别名...])；多别名取第一个能取到的
_ODF_SPECS = [
    ("开机LOGO", ["logovalue", "needlogo"]), ("品牌", ["prodbrand"]),
    ("遥控器LOGO品牌", ["remlgbr"]), ("遥控器加印LOGO", ["remaddlg"]),
    ("遥控器型号", ["remmodel"]), ("客户型号", ["prodcustomermodel"]),
    ("型号", ["prodmodel"]), ("机芯", ["prodchassis"]),
    ("屏编码", ["panelcode"]), ("复合贴纸", ["compositetags"]),
    ("销往地", ["soldto"]), ("国家/地区", ["countrycode"]),
    ("额定电压", ["ratedvoltage"]), ("电源插座", ["powplug"]),
    ("OSD语言出厂设置", ["osdsetup"]), ("必须支持语言", ["osdtype"]),
    ("交货日期", ["requireddeliverydate"]), ("订单数量", ["quantity"]),
    ("SKD出货模式", ["skddm"]), ("特殊要求", ["headremark1", "headremark2",
                                             "headremark3", "headremark4"]),
]


def _transform(val: Any, kind: str, mapping: dict) -> Optional[str]:
    if val in (None, ""):
        return None
    if kind == "coord":
        try:
            return _num(float(str(val).strip()) * 1000.0)
        except ValueError:
            return str(val)
    if kind == "num":
        return _num(val)
    if kind == "bool":
        try:
            return "开(1)" if float(str(val).strip()) != 0 else "关(0)"
        except ValueError:
            return str(val)
    if kind == "bool_inv":
        try:
            return "开(功能有)" if float(str(val).strip()) != 0 else "关(无)"
        except ValueError:
            return str(val)
    if kind == "map":
        return mapping.get(str(val).strip(), str(val))
    return str(val)


def _add_mid_fields(out: dict[str, str], mid: dict[str, str]) -> None:
    for name, key in _MID_SPECS:
        value = mid.get(key)
        if value not in (None, ""):
            out[name] = str(value).strip()


def _add_white_fields(out: dict[str, str], white: dict[str, str]) -> None:
    for name, key, kind, mapping in _WHITE_SPECS:
        value = _transform(white.get(key), kind, mapping)
        if value and name not in out:
            out[name] = value


def _add_key_fields(out: dict[str, str], mid: dict[str, str]) -> None:
    for name, key in _KEY_SPECS:
        value = mid.get(key)
        if value is not None:
            out[name] = "有(%s)" % value if str(value).strip() else "有"


def _add_odf_fields(out: dict[str, str], odf: dict[str, str]) -> None:
    for name, aliases in _ODF_SPECS:
        value = next((odf.get(alias) for alias in aliases if odf.get(alias)), None)
        if value:
            out[name] = value


def _add_wireless_fields(out: dict[str, str], rows: list[dict]) -> None:
    wireless = detect_wireless_rows(rows)
    if not rows:
        return

    if wireless["wifi"]:
        chipset = wireless["chipset"]
        out["无线模组"] = "有(%s)" % chipset if chipset else "有"
    elif wireless["chip_evidence"] or wireless["text_evidence"]:
        # 双证据未闭合：只有芯片、或只有文案/模组标记，不轻易判「有」。
        why = "仅芯片" if wireless["chip_evidence"] else "仅文案"
        out["无线模组"] = "待确认(%s)" % why
    else:
        out["无线模组"] = "无"
        return

    out["蓝牙"] = "有" if wireless["bt"] else "无"
    if wireless["wifi6"] is True:
        out["WiFi6"] = "有"
    elif wireless["wifi6"] is False:
        out["WiFi6"] = "无"
    else:
        out["WiFi6"] = out.get("WIFI6模块") or "待确认(芯片未登记)"


def fetch_fields(batch: str, with_side_label: bool = True) -> dict[str, str]:
    """取一个批次的全部参数，返回有序 dict（键名/顺序即邮件契约）。"""
    miss = mes_env.missing_required(("TIOT_URL", "MID_API_URL"))
    if miss:
        raise RuntimeError("端点未注入，缺失: %s" % ", ".join(miss))

    cleaned = clean_batch(batch)
    bom = fetch_bom_by_batch(cleaned)
    if not bom:
        raise RuntimeError("无法由批次 %s 解析 BOM" % batch)

    white = fetch_white(cleaned, bom)
    mid = fetch_mid_by_bom(bom)
    odf = fetch_odf(cleaned)

    out: dict[str, str] = {}
    out["批次"] = "%s（清洗后 %s）" % (str(batch).strip(), cleaned)
    out["BOM"] = bom
    bdesc = white.get("strBomdesc") or ""
    parts = str(bdesc).strip().split("/")
    if len(parts) > PLATFORM_SEGMENT:
        plat = parts[PLATFORM_SEGMENT].strip()
        if plat:
            out["产品平台"] = plat

    _add_mid_fields(out, mid)
    _add_white_fields(out, white)
    _add_key_fields(out, mid)
    _add_odf_fields(out, odf)

    # 料单只拉一次：侧标样式与无线模组判定共用
    rows = fetch_bom_rows(cleaned) if with_side_label else []

    _add_wireless_fields(out, rows)

    if with_side_label:
        sl = side_label_from_rows(rows)
        if sl:
            out["侧标样式"] = sl

    return out



# strBomdesc 只可靠到"下标 1 是产品平台"（与邮件口径同一约定 PLATFORM_SEGMENT）。
# 分段语义随产品族不同而不同，实测两种格式：
#   TK1N2753850ED4/TK1N2/RU/GunColor/TCL/75Q7D Pro/Northwest Asia/QFX2.0
#   65R69B Ultra/TK1N2/Black/FFALCON/AM4.0/HTPanel/2G
# 因此**不按位置猜字段名**：猜错过（把 HTPanel 当机型名并挤掉 MID 权威值）。
# 其余段以 BOM描述 原串输出，交给人判断。

# BOM 模式取不到的字段：ODF 与料单/侧标接口只认批次号，不认 BOM。
BOM_MODE_UNAVAILABLE = ("批次", "客户型号", "开机LOGO", "遥控器LOGO品牌", "遥控器加印LOGO",
                        "遥控器型号", "机芯", "屏编码", "复合贴纸", "销往地", "额定电压",
                        "电源插座", "OSD语言出厂设置", "必须支持语言", "交货日期",
                        "订单数量", "SKD出货模式", "特殊要求", "侧标样式")


def fetch_fields_by_bom(bom: str) -> dict[str, str]:
    """按 BOM 号直查参数（批次号未知时的入口）。

    与 fetch_fields 复用同一套 _MID_SPECS/_WHITE_SPECS/_KEY_SPECS 映射，
    因此字段名与口径和邮件完全一致；差异只在覆盖范围：
    ODF 订单类与侧标字段按批次取数，本函数取不到（见 BOM_MODE_UNAVAILABLE）。
    """
    miss = mes_env.missing_required(("TIOT_URL",))
    if miss:
        raise RuntimeError("端点未注入，缺失: %s" % ", ".join(miss))

    b = str(bom).strip().upper()
    if not b:
        raise RuntimeError("BOM 号为空")
    white = fetch_white("", b)
    if not white:
        raise RuntimeError("BOM %s 未查到白平衡参数" % b)
    mid = fetch_mid_by_bom(b)

    out: dict[str, str] = {"BOM": b}

    _add_mid_fields(out, mid)
    _add_white_fields(out, white)
    _add_key_fields(out, mid)

    segs = [s.strip() for s in str(white.get("strBomdesc") or "").split("/")]
    if len(segs) > PLATFORM_SEGMENT and segs[PLATFORM_SEGMENT]:
        out.setdefault("产品平台", segs[PLATFORM_SEGMENT])
    bdesc = "/".join(x for x in segs if x)
    if bdesc:
        out["BOM描述"] = bdesc
    return out


def _query_many(values: list[str], bom_mode: bool) -> list[dict]:
    fetch = fetch_fields_by_bom if bom_mode else fetch_fields
    results = []
    for value in values:
        try:
            results.append({"batch": value, "fields": fetch(value), "error": None})
        except Exception as exc:
            results.append({
                "batch": value,
                "fields": {},
                "error": "%s: %s" % (type(exc).__name__, str(exc)[:200]),
            })
    return results


def _print_plain(results: list[dict], bom_mode: bool, output_format: str) -> None:
    if bom_mode:
        print("说明：以下为 BOM 模式，ODF 订单与侧标类字段（%s 等 %d 项）按批次取数，"
              "本模式取不到；需要这些字段请改用批次号查询。\n"
              % ("、".join(BOM_MODE_UNAVAILABLE[:6]), len(BOM_MODE_UNAVAILABLE)))

    label = "BOM" if bom_mode else "批次"
    for result in results:
        print("== %s %s ==" % (label, result["batch"]))
        if result["error"]:
            print("  查询失败: %s" % result["error"])
            continue
        fields = result["fields"]
        for index, (key, value) in enumerate(fields.items(), 1):
            if output_format == "md":
                if index == 1:
                    print("| # | 字段 | 值 |\n|---|------|----|")
                print("| %d | %s | %s |" % (index, key, value))
            else:
                print("%2d. %s = %s" % (index, key, value))
        print("  （共 %d 字段）" % len(fields))


# ---------------------------------------------------------------------------
# CLI：单/多批次查询（全量输出，运维与人工核对面用；邮件路径不经过这里）
# 约定：查到多少字段就输出多少字段，禁止摘要、截断或挑选展示。
# ---------------------------------------------------------------------------
def _parse_cli_args():
    import argparse
    ap = argparse.ArgumentParser(
        prog="python3 -m wb_mail.mes_api",
        description="批次参数查询，单/多批次全量输出所有字段。"
                    "示例：python3 -m wb_mail.mes_api GLW500303A GLW500304A")
    ap.add_argument("batches", nargs="+", metavar="批次号",
                    help="一个或多个批次号，多批次逐个输出、失败互不影响")
    ap.add_argument("--bom", action="store_true",
                    help="入参按 BOM 号解释（默认按批次号）；BOM 模式取不到 ODF 订单与侧标字段")
    ap.add_argument("--format", choices=("text", "md", "json", "mail"), default="mail",
                    help="mail=与邮件同构(摘要+总览+逐批明细，默认)；md=单表；text=逐行键值；json=原始")
    return ap.parse_args()


def _print_mail(results: list[dict], bom_mode: bool) -> None:
    from wb_mail import mail_assembler
    pairs = [(result["batch"], result["fields"] or None) for result in results]
    note = ""
    if bom_mode:
        note = "BOM 模式：ODF 订单与侧标类字段按批次取数，本模式取不到。"
    print(mail_assembler.to_markdown(
        pairs, title="%s查询" % ("BOM" if bom_mode else "批次"), note=note
    ))


def _cli():
    args = _parse_cli_args()

    mes_env.load()
    required = ("TIOT_URL",) if args.bom else ("TIOT_URL", "MID_API_URL")
    miss = mes_env.missing_required(required)
    if miss:
        raise SystemExit("端点未注入，缺失: %s（T盘 wb-mail/wb_endpoints.env 应含这些键）"
                         % ", ".join(miss))

    results = _query_many(args.batches, args.bom)

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not any(r["error"] for r in results) else 2)

    if args.format == "mail":
        _print_mail(results, args.bom)
        raise SystemExit(0 if not any(r["error"] for r in results) else 2)

    _print_plain(results, args.bom, args.format)
    raise SystemExit(0 if not any(r["error"] for r in results) else 2)


if __name__ == "__main__":
    _cli()
