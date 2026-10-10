"""wb_mail v6 凭据 T盘加载模块。

优化点：
- 下载前校验 token 格式，无效 token 快速失败而非空转超时
- 明确区分超时/文件空/网络错误，日志记录具体原因
- 注入 env 时仅记录 key 名称，绝不泄露 value
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Optional

from wb_mail import config as C

log = C.log

PAN_ENV_PATHS = [p for p in (
    os.environ.get("WB_CREDENTIALS_PAN_PATH"),
    # 默认落盘位置就是 password.env；password/.env 是早期部署形态，仅作兜底。
    "self:7378655030280192/password.env",
    "self:7378655030280192/password/.env",
) if p]
PAN_ENV_PATH = PAN_ENV_PATHS[0]
CONFIG = os.path.expanduser("~/.tchat-cli/config.yaml")
# T-Doc token 实测可含 '@' '.' '+' '/' '=' 等字符，不能按纯字母数字下划线校验。
# v5.0.0 曾用 ^[A-Za-z0-9_\\-]{16,}$ 过严，导致真实 token 被拒、T盘兜底静默失效。
_MIN_TOKEN_LEN = 8
_PLACEHOLDER = re.compile(r"^(your|xxx+|todo|placeholder|none|null|<.*>)", re.I)


def _token_looks_valid(tok: str) -> bool:
    """宽松但有效的校验：长度下限 + 无空白/控制字符 + 非占位符。"""
    if len(tok) < _MIN_TOKEN_LEN:
        return False
    if re.search(r"[\s\x00-\x1f]", tok):
        return False
    if _PLACEHOLDER.match(tok):
        return False
    return True


def _tdoc_token() -> Optional[str]:
    """读取 tchat-cli 配置中的 tdoc_token，格式校验不通过返回 None。"""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("tdoc_token"):
                    tok = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if _token_looks_valid(tok):
                        return tok
                    log.warning(
                        "T盘 token 无效（长度 %d），跳过；未登录请执行 "
                        "tchat-cli pan token get --access-token $TCHAT_TOKEN",
                        len(tok),
                    )
                    return None
    except OSError:
        log.debug("未找到 tchat-cli 配置文件: %s", CONFIG)
    return None


def fetch_env_text() -> Optional[str]:
    """下载 T盘 .env，返回文本；按候选路径依次尝试，全失败返回 None。"""
    tok = _tdoc_token()
    if not tok:
        return None

    for pan_path in PAN_ENV_PATHS:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".env")
        tmp.close()
        try:
            try:
                proc = subprocess.run(
                    ["tchat-cli", "pan", "file", "download",
                     "--token", tok, "--path", pan_path, "--output", tmp.name],
                    capture_output=True, text=True, timeout=30)
                if proc.returncode != 0:
                    log.warning("T盘下载失败 rc=%d path=%s: %s", proc.returncode,
                                pan_path, (proc.stderr or proc.stdout or "")[:200])
                    continue
            except subprocess.TimeoutExpired:
                # CLI 偶尔下载完成但不退出，继续检查文件
                log.debug("T盘下载超时，检查文件是否已落盘")
            except FileNotFoundError:
                log.warning("tchat-cli 未安装，无法使用T盘兜底")
                return None

            if os.path.getsize(tmp.name) > 0:
                with open(tmp.name, encoding="utf-8", errors="replace") as fh:
                    return fh.read()
            log.warning("T盘 .env 下载为空文件 path=%s", pan_path)
        except OSError as e:
            log.warning("T盘兜底 IO 错误: %s", e)
        finally:
            try:
                os.remove(tmp.name)
            except OSError:
                pass
    return None


def fetch_into_environ(override: bool = False) -> list[str]:
    """把 T盘 .env 的 KEY=*** 注入 os.environ；返回注入的键名列表（不含值）。"""
    txt = fetch_env_text()
    if not txt:
        return []
    out: list[str] = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and (override or k not in os.environ):
            os.environ[k] = v
            out.append(k)
    if out:
        log.info("T盘兜底注入键: %s", ", ".join(out))
    return out
