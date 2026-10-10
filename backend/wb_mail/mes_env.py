"""wb_mail v6 端点注入模块。

MES/白平衡/ODF/料单 的接口地址与密钥**不写入代码包**，运行时从 T盘私有目录
拉取并注入 os.environ。与 SMB 口令同一套路（见 creds_pan）。

T盘文件：wb-mail 目录下的 wb_endpoints.env，键：
    TIOT_URL / MID_API_URL / ODF_URL / MES_API_BASE /
    MES_DOMAIN / MES_REFERER / WB_SMB_HOST / WB_MAIL_SEND_URL
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Optional

from wb_mail import config as C
from wb_mail.creds_pan import _tdoc_token

log = C.log

PAN_ENDPOINTS_PATH = os.environ.get(
    "WB_ENDPOINTS_PAN_PATH", "self:7378655030280192/wb-mail/wb_endpoints.env")
_TIMEOUT = int(os.environ.get("WB_ENDPOINTS_TIMEOUT", "30"))

# 查询批次与按 BOM 查询所需端点不同；调用方必须按场景校验，避免让
# “按批次查参数”错误依赖 SMB，也避免把可降级的 ODF/料单端点当硬失败。
QUERY_REQUIRED = ("TIOT_URL", "MID_API_URL")
LIVE_REQUIRED = QUERY_REQUIRED + ("WB_SMB_HOST",)


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def load(override: bool = False) -> dict[str, str]:
    """拉取并注入端点配置，返回本次注入的键名（**不含值**）。

    已存在于环境中的键默认不覆盖，便于临时实验时手工指定。
    """
    tok = _tdoc_token()
    if not tok:
        log.warning("端点注入跳过：T-Doc token 不可用（请执行 "
                    "tchat-cli pan token get --access-token $TCHAT_TOKEN）")
        return {}

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".env")
    tmp.close()
    try:
        try:
            proc = subprocess.run(
                ["tchat-cli", "pan", "file", "download",
                 "--token", tok, "--path", PAN_ENDPOINTS_PATH, "--output", tmp.name],
                capture_output=True, text=True, timeout=_TIMEOUT)
            if proc.returncode != 0:
                log.warning("端点文件下载失败 rc=%d: %s", proc.returncode,
                            (proc.stderr or proc.stdout or "")[:200])
                return {}
        except subprocess.TimeoutExpired:
            log.debug("端点下载超时，检查是否已落盘")
        except FileNotFoundError:
            log.warning("tchat-cli 未安装，无法拉取端点配置")
            return {}

        if os.path.getsize(tmp.name) <= 0:
            log.warning("端点文件为空")
            return {}
        with open(tmp.name, encoding="utf-8", errors="replace") as fh:
            kv = _parse(fh.read())
    except OSError as e:
        log.warning("端点注入 IO 错误: %s", e)
        return {}
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    injected: list[str] = []
    for k, v in kv.items():
        if override or k not in os.environ:
            os.environ[k] = v
            injected.append(k)
    if injected:
        log.info("端点注入键: %s", ", ".join(sorted(injected)))
    return {k: "injected" for k in injected}


def missing_required(keys: tuple[str, ...] = QUERY_REQUIRED) -> list[str]:
    """返回指定场景缺失的端点名。默认校验按批次查询所需端点。"""
    return [k for k in keys if not (os.environ.get(k) or "").strip()]


# token-proxy 换票协议元数据（不含任何密钥；base_url 由注入的 MES_DOMAIN 生成，
# 因此代码包内不落任何内网域名明文）。
TOKEN_CFG = {
    "auth_query_params": {"client_id": "MES"},
    "auth_path": "/oauth/public/getPlatformTokenInfo",
    "token_path": "accessToken",
    "token_type_path": "tokenType",
    "token_key_path": "tokenKey",
    "cache_ttl": 1800,
    "auth_contact": "MES 管理员（工单/批次料单菜单权限）",
}


def ensure_token_config() -> str:
    """按注入的 MES_DOMAIN 生成临时 assets/config.json，返回其路径。

    token-proxy 的 auth_session(skill_dir=...) 依赖该文件定位换票接口；
    缺失时换票会静默返回未鉴权 Session（表现为料单 401）。配置写入临时目录，
    避免运行时把内网域名写回可分发的技能包。
    """
    import json as _json
    root = os.environ.get("WB_TOKEN_CONFIG_DIR") or os.path.join(
        tempfile.gettempdir(), "wb_mail_token_proxy")
    assets = os.path.join(root, "assets")
    cfg_path = os.path.join(assets, "config.json")
    domain = get("MES_DOMAIN")
    if not domain:
        return ""
    cfg = dict(TOKEN_CFG)
    cfg["base_url"] = "https://" + domain
    try:
        os.makedirs(assets, exist_ok=True)
        old = ""
        if os.path.isfile(cfg_path):
            with open(cfg_path, encoding="utf-8") as fh:
                old = fh.read()
        new = _json.dumps(cfg, ensure_ascii=False, indent=2)
        if old != new:
            with open(cfg_path, "w", encoding="utf-8") as fh:
                fh.write(new)
            log.info("已生成临时换票配置: %s", cfg_path)
    except OSError as e:
        log.warning("生成换票配置失败: %s", e)
        return ""
    return cfg_path


def get(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()
