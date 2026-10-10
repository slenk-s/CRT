"""wb_mail v6 名单实时拉取模块（T盘）。

名单由业务侧在 T盘 wb-mail 目录长期维护，人员与线体会随时调整。
定时任务必须在每次发送前拉取最新一份，严禁只依赖代码包内烤死的副本——
实测本地包内名单（6334 字节）与 T盘最新版（6652 字节）已经不一致。

拉取失败时默认终止；只有显式设置 WB_ALLOW_LOCAL_CONTACTS=1 才允许上层回退到
--contacts 指定的本地文件，并在汇总 JSON 的 contacts_source 中标明风险。
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from wb_mail import config as C
from wb_mail.creds_pan import _tdoc_token

log = C.log

# T盘分享目录 /wb-mail 下的名单文件
PAN_CONTACTS_PATH = os.environ.get(
    "WB_PAN_CONTACTS_PATH",
    "self:7378655030280192/wb-mail/contacts_template.xlsx",
)
_TIMEOUT = int(os.environ.get("WB_PAN_CONTACTS_TIMEOUT", "40"))


def fetch_contacts(dest_dir: str) -> tuple[Optional[str], str]:
    """从 T盘下载名单到 dest_dir。

    返回 (本地路径 或 None, 来源说明)。来源说明一定会被写进日志和汇总，
    失败原因不能只停留在 debug 级。
    """
    tok = _tdoc_token()
    if not tok:
        return None, "T盘token不可用(未执行 tchat-cli pan token get)"

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        return None, "创建名单目录失败: %s" % e

    dest = os.path.join(dest_dir, os.path.basename(PAN_CONTACTS_PATH))
    try:
        os.remove(dest)          # 防止上一次残留被当成本次成功
    except OSError:
        pass

    err = ""
    timed_out = False
    try:
        proc = subprocess.run(
            ["tchat-cli", "pan", "file", "download",
             "--token", tok, "--path", PAN_CONTACTS_PATH, "--output", dest],
            capture_output=True, text=True, timeout=_TIMEOUT)
        rc = proc.returncode
        err = (proc.stderr or proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        # CLI 偶发下载完成但不退出：不直接判失败，继续用文件大小校验
        rc, timed_out = -1, True
    except FileNotFoundError:
        return None, "tchat-cli未安装，无法拉取T盘名单"
    except OSError as e:
        return None, "T盘名单下载IO错误: %s" % e

    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        why = err[:160] if err else ("超时" if timed_out else "无输出")
        return None, "T盘名单下载失败 rc=%s：%s" % (rc, why)

    return dest, "T盘 %s（%d 字节）" % (PAN_CONTACTS_PATH, os.path.getsize(dest))
