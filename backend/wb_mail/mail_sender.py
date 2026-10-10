"""wb_mail v6 邮件发送模块。

优化点：
- 发送前 preflight 检查 tchat-cli 是否存在，快速失败并给出安装指引
- 错误分类：区分"命令不存在"/"参数错误"/"网络失败"/"超时"
- 可配置发送超时（默认 120s → v5 60s，避免单封卡住整体流程）
- 返回结构化结果 dict 而非裸 (rc, output)
- v6.1 双通道投递：正文超过 120KB 时改走邮件网关 HTTP 接口。
  原因不是"HTTP 更快"，而是 **argv 装不下**：Linux 单个参数上限
  MAX_ARG_STRLEN = 128KB（32 页），而 tchat-cli 只有 `--body`、没有
  `--body-file`。日报正文按线体累积批次明细，UTF-8 中文每字 3 字节，
  超过约 4 万汉字即触顶，子进程直接 `OSError [Errno 7] Argument list too long`
  （实测 120KB 通过、130KB 失败）。HTTP 通道把正文放进 POST body，
  只受网关自身大小限制。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from wb_mail import config as C
from wb_mail import mes_env

log = C.log

SEND_TIMEOUT = int(__import__("os").environ.get("WB_SEND_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# 通道选择（阈值按 **字节** 计，不是字符数；中文正文 1 字 = 3 字节）
# ---------------------------------------------------------------------------
# Linux MAX_ARG_STRLEN = 32 * 4096 = 131072B ≈ 128KB。默认阈值 120KB，
# 留 ~8KB 余量：主题、收件人等同类参数与编码差异都可能吃掉这点空间。
DEFAULT_HTTP_THRESHOLD_KB = 120
# 阈值可调（排障用），不必改代码：WB_BODY_HTTP_THRESHOLD_KB=200
# 调高前请确认执行环境单个 argv 上限，Linux 上 128KB 是内核硬上限，调不过去。

CLI_CHANNEL = "cli"
HTTP_CHANNEL = "http"

# 端点与鉴权。按包内约定，端点不留默认值，只能由 T盘 wb_endpoints.env 注入
# （见 references/architecture.md 端点注入清单）。
SEND_URL_KEY = "WB_MAIL_SEND_URL"       # 完整地址，例 <网关>/hestia/app/exchange/mail/send
TOKEN_KEYS = ("TCHAT_TOKEN", "TCHAT_ACCESSTOKEN")


def http_threshold_bytes() -> int:
    """当前生效的大正文阈值（字节）。环境变量非法时回落默认值并告警。"""
    raw = (os.environ.get("WB_BODY_HTTP_THRESHOLD_KB") or "").strip()
    if not raw:
        return DEFAULT_HTTP_THRESHOLD_KB * 1024
    try:
        kb = int(raw)
    except ValueError:
        log.warning("WB_BODY_HTTP_THRESHOLD_KB=%r 不是整数，按默认 %dKB 处理",
                    raw, DEFAULT_HTTP_THRESHOLD_KB)
        return DEFAULT_HTTP_THRESHOLD_KB * 1024
    if kb < 1:
        log.warning("WB_BODY_HTTP_THRESHOLD_KB=%d 无意义，按默认 %dKB 处理",
                    kb, DEFAULT_HTTP_THRESHOLD_KB)
        return DEFAULT_HTTP_THRESHOLD_KB * 1024
    return kb * 1024


def body_bytes(text: str) -> int:
    """正文 UTF-8 字节数。argv 传参受内核限制的是字节，不是字符。"""
    return len((text or "").encode("utf-8", "replace"))


def pick_channel(nbytes: int, attach_path: str | None = None) -> str:
    """按正文体积选投递通道。

    带附件时仍走 CLI：附件接口是 multipart，CLI 负责组装文件分片，
    日报链路本身不发附件（`daily_job` 不传 `attach_path`），因此这里
    把附件视为"必须 CLI"的显式约束，而不是悄悄换协议。
    """
    if nbytes > http_threshold_bytes():
        return CLI_CHANNEL if attach_path else HTTP_CHANNEL
    return CLI_CHANNEL


# ---------------------------------------------------------------------------
# CLI 通道（tchat-cli email send）
# ---------------------------------------------------------------------------
def _join(addrs: list[str]) -> str:
    return ",".join(a for a in addrs if a)


def build_cmd(subject: str, to: list[str], cc: list[str],
              body_html: str, attach_path: str | None = None) -> list[str]:
    """构造 tchat-cli email send 的 argv 列表（纯函数，可单测）。"""
    cmd = ["tchat-cli", "email", "send",
           "--to", _join(to),
           "--subject", subject,
           "--body", body_html,
           "--html"]
    if cc:
        cmd += ["--cc", _join(cc)]
    if attach_path:
        cmd += ["--attachments", attach_path]
    return cmd


def preflight() -> str | None:
    """检查 tchat-cli 可用性。返回 None 表示正常，否则返回错误描述。"""
    if shutil.which("tchat-cli") is None:
        return "tchat-cli 未安装或不在 PATH 中。请运行: pip install tchat-cli 或检查 PATH"
    return None


def _send_cli(result: dict[str, Any], subject: str, to: list[str], cc: list[str],
              body_html: str, attach_path: str | None, timeout: int) -> dict[str, Any]:
    err = preflight()
    if err:
        result["error_type"] = "not_installed"
        result["output"] = err
        log.error("发送预检失败: %s", err)
        return result

    cmd = build_cmd(subject, to, cc, body_html, attach_path)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        result["rc"] = proc.returncode
        result["output"] = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0:
            result["ok"] = True
            log.info("邮件已发送(cli): %s -> %s", subject[:40], _join(to))
        else:
            result["error_type"] = "send_failed"
            log.error("发送失败 rc=%d: %s", proc.returncode, result["output"][:200])
    except subprocess.TimeoutExpired:
        result["error_type"] = "timeout"
        result["output"] = f"发送超时({timeout}s)"
        log.error("邮件发送超时: %s", subject[:40])
    except FileNotFoundError:
        result["error_type"] = "not_installed"
        result["output"] = "tchat-cli 执行时找不到（可能 PATH 变化）"
        log.error("tchat-cli 文件未找到")
    except OSError as e:
        # Errno 7 (E2BIG, Argument list too long) 会落到这里：正文过大。
        # 正常配置下不会走到（超阈值已切 HTTP），走到即说明阈值被调高或
        # 带附件，错误文案里要点名这一点。
        result["error_type"] = "os_error"
        result["output"] = f"{e}（正文 {result['body_bytes']}B，" \
                           f"阈值 {http_threshold_bytes()}B）"
        log.error("发送 IO 错误: %s", e)

    return result


# ---------------------------------------------------------------------------
# HTTP 通道（邮件网关 JSON 接口，正文进 POST body 而非 argv）
# ---------------------------------------------------------------------------
def _strip_bearer(value: str) -> str:
    return re.sub(r"(?i)^bearer\s+", "", value.strip())


def _token_from_cli_config() -> str:
    """兜底：读 tchat-cli 配置文件里的 access_token（与 CLI 同一凭证来源）。"""
    path = Path.home() / ".tchat-cli" / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        key, sep, val = line.partition(":")
        if sep and key.strip() == "access_token":
            return val.strip().strip('"').strip("'")
    return ""


def http_token() -> str:
    """取 T信 token；容器环境变量优先，且必须去掉可能存在的 bearer 前缀。"""
    for key in TOKEN_KEYS:
        token = _strip_bearer(os.environ.get(key) or "")
        if token:
            return token
    return _strip_bearer(_token_from_cli_config())


def http_config_error() -> str | None:
    """HTTP 通道可用性检查。返回 None 表示可用，否则返回缺失说明。"""
    if not mes_env.get(SEND_URL_KEY):
        return (f"缺少邮件 HTTP 端点 {SEND_URL_KEY}"
                "（请在T盘 wb-mail/wb_endpoints.env 配置后重跑）")
    if not http_token():
        return ("缺少 T信鉴权 TCHAT_TOKEN/TCHAT_ACCESSTOKEN"
                "（或 tchat-cli 配置文件 access_token）")
    return None


def _http_post(url: str, payload: dict[str, Any], token: str,
               timeout: int) -> Any:
    """单次 POST JSON。**故意不重试**：投递一次是硬约束（见 SKILL.md 不变量）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "accessToken": token})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw)


def _send_http(result: dict[str, Any], subject: str, to: list[str], cc: list[str],
               body_html: str, timeout: int) -> dict[str, Any]:
    missing = http_config_error()
    if missing:
        # 不静默退回 CLI：大正文退回去只会撞上 ARG_MAX，错误更难定位。
        result["error_type"] = "http_not_configured"
        result["output"] = (f"{missing}；正文 {result['body_bytes']}B 已超过 "
                            f"argv 阈值 {http_threshold_bytes()}B，无法改走命令行通道")
        log.error("HTTP 通道不可用: %s", result["output"])
        return result

    payload: dict[str, Any] = {
        "toRecipients": [a for a in to if a],
        "subject": subject,
        "body": body_html,
        "isHtml": True,
    }
    if cc:
        payload["ccRecipients"] = [a for a in cc if a]

    url = mes_env.get(SEND_URL_KEY)
    token = http_token()
    try:
        resp = _http_post(url, payload, token, timeout)
    except urllib.error.HTTPError as e:
        result["rc"] = e.code
        result["output"] = f"HTTP {e.code}: {str(e.reason)[:120]}"
        result["error_type"] = "auth_expired" if e.code in (401, 403) else "send_failed"
        # 网关已收到请求，5xx 也可能已投递 → 结果未知，禁止自动重试。
        result["unconfirmed"] = e.code >= 500
        log.error("HTTP 发送失败 %s: %s", subject[:40], result["output"])
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        timed_out = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
        result["error_type"] = "timeout" if timed_out else "network_error"
        result["output"] = (f"{'发送超时' if timed_out else '网络失败'}({timeout}s): "
                            f"{type(e).__name__}: {str(e)[:120]}")
        result["unconfirmed"] = True
        log.error("HTTP 投递结果未知(%s): %s", result["error_type"], subject[:40])
    except json.JSONDecodeError as e:
        result["error_type"] = "bad_response"
        result["output"] = f"响应非 JSON: {str(e)[:120]}"
        result["unconfirmed"] = True
        log.error("HTTP 响应解析失败: %s", subject[:40])
    else:
        result["rc"] = 0
        result["output"] = json.dumps(resp, ensure_ascii=False)[:500]
        code = str(resp.get("code", "")) if isinstance(resp, dict) else ""
        data = resp.get("data") if isinstance(resp, dict) else None
        success = not (isinstance(data, dict) and data.get("success") is False)
        if code == "0" and success:
            result["ok"] = True
            log.info("邮件已发送(http): %s -> %s (%.0fKB)",
                     subject[:40], _join(to), result["body_bytes"] / 1024)
        else:
            result["error_type"] = "send_failed"
            msg = (resp.get("msg") if isinstance(resp, dict) else "") or "无响应说明"
            log.error("HTTP 网关拒绝 code=%s msg=%s: %s", code, str(msg)[:120],
                      subject[:40])

    if result.get("unconfirmed"):
        result["output"] += "｜投递结果未知，禁止重试；请核对 `tchat-cli email sent`"
    return result


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def send(subject: str, to: list[str], cc: list[str],
         body_html: str, attach_path: str | None = None,
         timeout: int | None = None) -> dict[str, Any]:
    """真实发送。返回
    ``{"ok": bool, "rc": int, "output": str, "error_type": str|None,
       "channel": "cli"|"http", "body_bytes": int, "unconfirmed": bool}``。

    通道由正文体积决定：>阈值走 HTTP 接口，否则走 tchat-cli。
    两条通道都**不重试**（遵循 tchat-email 规则：一次投递）。
    """
    timeout = timeout or SEND_TIMEOUT
    nbytes = body_bytes(body_html)
    channel = pick_channel(nbytes, attach_path)
    result: dict[str, Any] = {
        "ok": False, "rc": -1, "output": "", "error_type": None,
        "channel": channel, "body_bytes": nbytes, "unconfirmed": False,
    }

    if not to:
        result["error_type"] = "missing_recipient"
        result["output"] = "收件人为空，拒绝发送"
        log.error(result["output"])
        return result

    if channel == HTTP_CHANNEL:
        log.info("大正文切 HTTP 通道: %.0fKB > %.0fKB",
                 nbytes / 1024, http_threshold_bytes() / 1024)
        return _send_http(result, subject, to, cc, body_html, timeout)

    if attach_path and nbytes > http_threshold_bytes():
        log.warning("正文 %.0fKB 超阈值但带附件，仍走 CLI（附件接口未实现 HTTP 通道）",
                    nbytes / 1024)
    return _send_cli(result, subject, to, cc, body_html, attach_path, timeout)
