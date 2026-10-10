"""wb_mail v6 配置模块。

优化点：
- 消除 load_smb_credentials / load_env 逻辑重复，统一为单一入口
- 路径支持环境变量覆盖，便于 CI / 定时任务灵活切换
- 集中日志配置，供全模块复用
- 新增版本号常量，交付包可自报版本
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 版本 & 日志
# ---------------------------------------------------------------------------
VERSION = "6.4.0"

_logger = logging.getLogger("wb_mail")


def setup_logging(level: str = "INFO", log_dir: Optional[str] = None) -> logging.Logger:
    """配置 wb_mail 全模块日志。log_dir 非空时同时写文件。"""
    _logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not _logger.handlers:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("[%(asctime)s %(levelname)s] %(name)s: %(message)s",
                                          datefmt="%H:%M:%S"))
        _logger.addHandler(sh)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, "wb_mail.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _logger.addHandler(fh)
    return _logger


log = _logger

# ---------------------------------------------------------------------------
# SMB 连接参数：主机由 T盘 wb_endpoints.env 注入 WB_SMB_HOST（见 mes_env），
# 共享/路径/车间模板在 wb_mail/assets/smb_config.json（非机密），口令走 SMB_PASSWORD。
# 此处不再保留任何内网地址默认值。
# ---------------------------------------------------------------------------
SMB_HOST = os.environ.get("WB_SMB_HOST", "")

# ---------------------------------------------------------------------------
# 正则（避免源码反斜杠在传输中翻倍）
# ---------------------------------------------------------------------------
_B = chr(92)
_DIG = _B + "d"

DATE_RE = "(" + _DIG + "{1,2})月(" + _DIG + "{1,2})[日号]"
COPY_RE = _B + "(" + "(" + _DIG + "+)" + _B + ")"
BOM_FILTER_RE = "^Z.U"
EMAIL_RE = "<([^<>]+@[^<>]+)>"

# ---------------------------------------------------------------------------
# 计划表解析
# ---------------------------------------------------------------------------
HEADER_ROW = 3
COL_LINE, COL_BATCH, COL_BOM = "线体", "批次号", "BOM"
COL_OWNER, COL_CC = "负责人", "抄送邮箱"
PILOT_MARK = "试产"

# ---------------------------------------------------------------------------
# 外部依赖路径（支持环境变量覆盖）
# ---------------------------------------------------------------------------
# 白平衡/MID/ODF/料单 取数内建于 wb_mail.mes_api，SMB 计划取数内建于 wb_mail.smb_plan，
# 端点与 SMB 主机运行时由 wb_mail.mes_env 从 T盘注入。
# 本包不含任何外部技能路径、端点、内网地址或密钥明文；WB_AGING_FETCHER 仅作应急覆盖。
AGING_FETCHER = os.environ.get(
    "WB_AGING_FETCHER",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "smb_plan.py"),
)
OUT_BASE = os.environ.get("WB_OUT_BASE", "/mnt/user-data/workspace/wb_mail_tmp")
CONTACTS_PATH = os.environ.get(
    "WB_CONTACTS",
    "/mnt/user-data/workspace/wb_mail/assets/contacts.xlsx",
)

# ---------------------------------------------------------------------------
# 邮件明细表：不展示的字段
# ---------------------------------------------------------------------------
# 两类原因：
#   1) 与总览表重复（如「侧标」总览已有该列）；
#   2) 对老化/白平衡调试无意义（WiFi/蓝牙/WiFi6 有无、工单号/条码类型等
#      其实是 MES 工单与条码的表头残留行，并非电视参数）。
# 逗号分隔，可用环境变量 WB_DETAIL_EXCLUDE 追加，不必改代码。
# 明细表额外排除：非电视调试参数的 MES 工单/条码残留行。
# 注意：与总览表重复的字段（色坐标/RGB/Gamma/亮度/面板/侧标等）不在这里维护，
# 由 mail_assembler.OVERVIEW_COLS 的 covers 声明自动去重。
# 注意：真实 MES 数据里「工单号」与「工单编号」两个键同时存在，必须都排除；
# 只写其中一个会漏掉另一个（历史上就因写成「工单号」而滤不掉「工单编号」）。
# 只排 MES 工单/条码子表带来的表头噪声。**不要**排 WiFi/WiFi6/蓝牙/无线模组——
# 那三项是 detect_wireless_rows() 由料单芯片算出的判定结果，排掉等于白算（邮件会漏发）。
_DETAIL_EXCLUDE_DEFAULT = "工单号,工单编号,条码类型,已打印,条码范围"

# 工单号形如 FA2609040212 / MZ2609040216（2 位大写字母 + 10 位数字）。
# 抓取器把 MES 工单子表的首列当成了字段名，于是每个工单号都变成明细里的一行；
# 这类键随每日计划变化，静态清单永远追不上，故按正则模式排除。
# 可用环境变量 WB_DETAIL_EXCLUDE_PATTERNS 逗号追加更多模式。
_DETAIL_EXCLUDE_PATTERNS_DEFAULT = r"^[A-Z]{2}\d{10}$"
DETAIL_EXCLUDE_PATTERNS: list[str] = (
    [_DETAIL_EXCLUDE_PATTERNS_DEFAULT]
    + [p.strip() for p in os.environ.get("WB_DETAIL_EXCLUDE_PATTERNS", "").split(",")
       if p.strip()]
)
DETAIL_EXCLUDE_KEYS = set(
    [k.strip() for k in _DETAIL_EXCLUDE_DEFAULT.split(",") if k.strip()]
    + [k.strip() for k in os.environ.get("WB_DETAIL_EXCLUDE", "").split(",")
       if k.strip()]
)

# ---------------------------------------------------------------------------
# WB 抓取控制参数
# ---------------------------------------------------------------------------
WB_TIMEOUT = int(os.environ.get("WB_TIMEOUT", "120"))       # 单批次超时秒数
WB_RETRIES = int(os.environ.get("WB_RETRIES", "2"))         # 失败重试次数
WB_PARALLEL = int(os.environ.get("WB_PARALLEL", "4"))       # 并行抓取线程数

# ---------------------------------------------------------------------------
# SMB 凭据加载（统一入口，消除 v4 中 load_env 重复）
# ---------------------------------------------------------------------------
_ENV_FILE_KEYS = ("WB_MAIL_ENV",)


def _env_candidates() -> list[str]:
    """凭据文件搜索路径（按优先级排列）。"""
    home = Path.home()
    out: list[str] = []
    for k in _ENV_FILE_KEYS:
        p = os.environ.get(k)
        if p:
            out.append(p)
    out.append(str(home / ".wb_mail" / ".env"))
    out.append("/mnt/user-data/workspace/.env")
    return out


def _parse_env_file(path: str) -> dict[str, str]:
    """解析 KEY=*** 文件，返回字典。"""
    result: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    result[key] = val
    except OSError as e:
        log.warning("读取凭据文件失败 %s: %s", path, e)
    return result


def load_credentials(override: bool = False) -> Optional[str]:
    """统一凭据加载入口（v5 替代 v4 的 load_smb_credentials + load_env）。

    优先级：$WB_MAIL_ENV → ~/.wb_mail/.env → workspace/.env → T盘。
    口令仅存内存，绝不落日志。
    返回实际加载的文件路径（或 "pan:/password/.env" 或 None）。
    """
    path: Optional[str] = None
    for candidate in _env_candidates():
        if os.path.isfile(candidate):
            path = candidate
            break

    if path:
        for key, val in _parse_env_file(path).items():
            if override or key not in os.environ:
                os.environ[key] = val
        log.debug("凭据已从 %s 加载", path)

    # T盘兜底：本地无 SMB_PASSWORD 时尝试
    if override or "SMB_PASSWORD" not in os.environ:
        try:
            from wb_mail import creds_pan
            if creds_pan.fetch_into_environ(override=override):
                path = path or "pan:password.env"
                log.debug("凭据已从T盘兜底加载")
        except Exception as e:
            log.debug("T盘兜底失败(可忽略): %s", e)

    return path


# 向后兼容别名（定时任务脚本可能仍引用旧名）
load_smb_credentials = load_credentials
load_env = load_credentials
