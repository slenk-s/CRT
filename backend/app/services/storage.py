#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
services/storage.py —— SMB 照片存储层（生产用）

职责：把照片按「日期/线体/批次/工位」归档到共享盘；提供 写/读/移动/删除/列目录。
约定：
  - 数据库里只存**共享内相对路径**（不含 host/share），保证可移植；
  - 真实读写时再拼成 UNC：\\\\{SMB_HOST}\\{SMB_SHARE}\\{SMB_ROOT}\\{rel}；
  - 草稿区：{SMB_ROOT}/_draft/{changeover_id}/{item_id}.jpg
  - 正式区：{SMB_ROOT}/{日期}/{线体}/{批次}/{工位}/{HHMMSS}_{工号}_v{版本}.jpg
  - 提交 = 同盘 rename（草稿 → 正式），代价低；纠错改版 = 写新版本文件。

配置（全部走环境变量，不写死）：
  SMB_HOST, SMB_SHARE, SMB_ROOT(=共享内子路径，如 "slenk_\\FA_ROOT"),
  SMB_USER, SMB_PASSWORD, SMB_DOMAIN(可选)

依赖：pip install smbprotocol

自检：
  python storage.py        # 连接 + 目录 + 写/读/移动/删 全链路
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
from contextlib import contextmanager
from typing import Iterator, Optional

try:
    import smbclient  # 来自 smbprotocol
except ImportError:  # pragma: no cover
    smbclient = None

# SMB 连接超时（秒）。默认值 60s 会让「共享盘不可达」的每次请求都长时间挂起
# （Windows 上实测约 20s），离线降级路径必须先等完这段时间；局域网内 5s 足够。
SMB_CONNECT_TIMEOUT = 5.0

def photo_display_name(batch: str, station: str, seq: int, ext: str) -> str:
    """统一命名：`{批次}_{工位}_{序号}.{ext}`（清理非法字符后拼接）。"""
    return "%s_%s_%d.%s" % (
        sanitize_segment(batch), sanitize_segment(station), int(seq), ext.lower()
    )

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_segment(s: str) -> str:
    """清理单个路径段中的非法字符（Windows/SMB 禁用字符与结尾点/空格）。"""
    s = _ILLEGAL.sub("_", str(s or "").strip())
    s = s.rstrip(". ")
    return s or "_"


class StorageError(RuntimeError):
    """存储层业务异常（上层据此返回 503『存储暂不可用』）。"""


class SmbStorage:
    def __init__(
        self,
        host: Optional[str] = None,
        share: Optional[str] = None,
        root: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> None:
        if smbclient is None:
            raise StorageError("缺少依赖：请先 pip install smbprotocol")
        self.host = host if host is not None else os.environ.get("SMB_HOST", "")
        self.share = share if share is not None else os.environ.get("SMB_SHARE", "")
        _root = root if root is not None else os.environ.get("SMB_ROOT", "")
        self.root = self._norm(_root)
        self.user = user if user is not None else os.environ.get("SMB_USER", "")
        self.password = password if password is not None else os.environ.get("SMB_PASSWORD", "")
        self.domain = domain if domain is not None else os.environ.get("SMB_DOMAIN", "")
        if not self.host or not self.share:
            raise StorageError("SMB_HOST / SMB_SHARE 未配置")
        self._registered = False

    # ---------- 基础 ----------
    @staticmethod
    def _norm(p: str) -> str:
        p = (p or "").replace("/", "\\")
        p = re.sub(r"\\+", "\\\\", p)  # 折叠重复反斜杠（PowerShell 里 \\ 会原样传入）
        return p.strip("\\")

    def _ensure(self) -> None:
        if not self._registered:
            # 注意：smbclient.register_session 不支持 domain 参数，域要拼进用户名
            username = self.user or None
            if username and self.domain:
                username = "%s\\%s" % (self.domain, username)
            try:
                smbclient.register_session(
                    self.host,
                    username=username,
                    password=self.password or None,
                    connection_timeout=SMB_CONNECT_TIMEOUT,
                )
            except Exception as e:  # noqa: BLE001
                raise StorageError("连接共享盘失败(%s): %s" % (type(e).__name__, e)) from e
            self._registered = True

    def rel(self, *parts: str) -> str:
        """拼共享内相对路径（自动带上 SMB_ROOT）。"""
        segs = [self.root] if self.root else []
        for p in parts:
            p = self._norm(p)
            if p:
                segs.append(p)
        return "\\".join(s for s in segs if s)

    def unc(self, rel: str = "") -> str:
        """共享内相对路径（**已含 SMB_ROOT**）→ UNC 绝对路径。"""
        base = "\\\\{}\\{}".format(self.host, self.share)
        rel = self._norm(rel)
        return base + ("\\" + rel if rel else "")

    def root_unc(self) -> str:
        """SMB_ROOT 对应的 UNC 绝对路径。"""
        return self.unc(self.root)

    # ---------- 路径构建 ----------
    def draft_rel(self, changeover_id: int, item_id: int, ext: str = "jpg") -> str:
        return self.rel("_draft", str(changeover_id), sanitize_segment("%s.%s" % (item_id, ext)))

    def final_rel(self, date: str, line: str, batch: str, station: str,
                  ts: str, emp_id: str, ver: int, ext: str = "jpg") -> str:
        name = "%s_%s_v%d.%s" % (sanitize_segment(ts), sanitize_segment(emp_id), int(ver), ext)
        return self.rel(sanitize_segment(date), sanitize_segment(line),
                        sanitize_segment(batch), sanitize_segment(station), name)

    @staticmethod
    def now_ts() -> str:
        return _dt.datetime.now().strftime("%H%M%S")

    # ---------- 读写 ----------
    def makedirs(self, rel: str) -> None:
        self._ensure()
        try:
            smbclient.makedirs(self.unc(rel), exist_ok=True)
        except Exception as e:  # noqa: BLE001
            raise StorageError("建目录失败(%s): %s" % (rel, e)) from e

    def write_bytes(self, rel: str, data: bytes) -> int:
        """写文件（自动建父目录）。返回字节数。"""
        self._ensure()
        unc = self.unc(rel)
        parent = unc.rsplit("\\", 1)[0]
        try:
            smbclient.makedirs(parent, exist_ok=True)
            with smbclient.open_file(unc, mode="wb") as f:
                f.write(data)
        except Exception as e:  # noqa: BLE001
            raise StorageError("写文件失败(%s): %s" % (rel, e)) from e
        return len(data)

    def read_bytes(self, rel: str) -> bytes:
        self._ensure()
        try:
            with smbclient.open_file(self.unc(rel), mode="rb") as f:
                return f.read()
        except Exception as e:  # noqa: BLE001
            raise StorageError("读文件失败(%s): %s" % (rel, e)) from e

    @contextmanager
    def open_stream(self, rel: str) -> Iterator[object]:
        """流式读取（供图片代理接口转发，避免整图入内存）。"""
        self._ensure()
        try:
            with smbclient.open_file(self.unc(rel), mode="rb") as f:
                yield f
        except Exception as e:  # noqa: BLE001
            raise StorageError("打开文件流失败(%s): %s" % (rel, e)) from e

    def exists(self, rel: str) -> bool:
        """存在即 True；连接失败/文件缺失都返回 False（不抛异常）。

        离线时调用方据此回退到本地存储，而不是让异常向上冒泡成 500。
        """
        try:
            self._ensure()
            smbclient.stat(self.unc(rel))
            return True
        except Exception:  # noqa: BLE001
            return False

    def reachable(self) -> bool:
        """轻量连通性探测：能建立会话并访问 SMB_ROOT 即视为在线。"""
        try:
            self._ensure()
            smbclient.stat(self.unc(self.root))
            return True
        except Exception:  # noqa: BLE001
            return False

    def move(self, src_rel: str, dst_rel: str) -> None:
        """同盘迁移（草稿 → 正式归档）。目标已存在会被覆盖。"""
        self._ensure()
        src, dst = self.unc(src_rel), self.unc(dst_rel)
        try:
            smbclient.makedirs(dst.rsplit("\\", 1)[0], exist_ok=True)
            if self.exists(dst_rel):
                smbclient.remove(dst)
            smbclient.rename(src, dst)
        except Exception as e:  # noqa: BLE001
            raise StorageError("移动文件失败(%s → %s): %s" % (src_rel, dst_rel, e)) from e

    def remove(self, rel: str) -> None:
        self._ensure()
        try:
            smbclient.remove(self.unc(rel))
        except Exception as e:  # noqa: BLE001
            raise StorageError("删除文件失败(%s): %s" % (rel, e)) from e

    def listdir(self, rel: Optional[str] = None) -> list[str]:
        """列目录；rel 为空时列 SMB_ROOT。"""
        self._ensure()
        target = self.unc(self.root if rel is None else rel)
        try:
            return sorted(smbclient.listdir(target))
        except Exception as e:  # noqa: BLE001
            raise StorageError("列目录失败(%s): %s" % (target, e)) from e

    def health_check(self) -> dict:
        """启动自检：返回 {ok, root, message}。"""
        try:
            self._ensure()
            self.makedirs(self.root)
            entries = self.listdir()
            return {"ok": True, "root": self.root_unc(), "items": len(entries),
                    "message": "SMB 可用（%d 项）" % len(entries)}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "root": self.root_unc(), "message": str(e)}


class LocalStorage:
    """本地临时照片目录（SMB 不可用时的降级）。

    目录结构刻意与 SmbStorage 的共享内相对路径保持一致，
    这样后台同步时可直接按 rel_path 搬运。
    """

    def __init__(self, root: str) -> None:
        self.root = str(root)
        try:
            os.makedirs(self.root, exist_ok=True)
        except OSError as e:
            raise StorageError("本地临时目录不可用: %s" % e) from e

    @staticmethod
    def _norm(p: str) -> str:
        p = (p or "").replace("/", os.sep)
        p = p.lstrip(os.sep)
        return os.path.normpath(p)

    def _abs(self, rel: str) -> str:
        rel = self._norm(rel)
        return os.path.join(self.root, rel)

    def rel(self, *parts: str) -> str:
        """按 rel_path 拼本地相对路径（不使用 SMB_ROOT 概念）。"""
        segs = []
        for p in parts:
            p = self._norm(p)
            if p:
                segs.append(p)
        return os.path.join(*segs)

    def write_bytes(self, rel: str, data: bytes) -> int:
        path = self._abs(rel)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            raise StorageError("本地写失败(%s): %s" % (rel, e)) from e
        return len(data)

    def read_bytes(self, rel: str) -> bytes:
        path = self._abs(rel)
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            raise StorageError("本地读失败(%s): %s" % (rel, e)) from e

    @contextmanager
    def open_stream(self, rel: str) -> Iterator[object]:
        path = self._abs(rel)
        try:
            with open(path, "rb") as f:
                yield f
        except OSError as e:
            raise StorageError("本地打开失败(%s): %s" % (rel, e)) from e

    def exists(self, rel: str) -> bool:
        return os.path.isfile(self._abs(rel))

    def remove(self, rel: str) -> None:
        path = self._abs(rel)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as e:
                raise StorageError("本地删除失败(%s): %s" % (rel, e)) from e

    def move(self, src_rel: str, dst_rel: str) -> None:
        src, dst = self._abs(src_rel), self._abs(dst_rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(dst):
                os.remove(dst)
            shutil.move(src, dst)
        except OSError as e:
            raise StorageError("本地移动失败(%s → %s): %s" % (src_rel, dst_rel, e)) from e

    def now_ts(self) -> str:
        return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    def root_abs(self) -> str:
        return os.path.abspath(self.root)

# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def _self_test() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="SmbStorage 自检（参数缺省时读环境变量）")
    ap.add_argument("--host", default=os.environ.get("SMB_HOST", ""))
    ap.add_argument("--share", default=os.environ.get("SMB_SHARE", ""))
    ap.add_argument("--root", default=os.environ.get("SMB_ROOT", ""), help=r'共享内子路径，如 "slenk_\\FA_ROOT"')
    ap.add_argument("--user", default=os.environ.get("SMB_USER", ""))
    ap.add_argument("--password", default=os.environ.get("SMB_PASSWORD", ""))
    ap.add_argument("--domain", default=os.environ.get("SMB_DOMAIN", ""))
    a = ap.parse_args()

    if not a.host or not a.share:
        print("未配置 SMB_HOST / SMB_SHARE。请二选一：")
        print('  1) 用参数：python storage.py --host 10.118.1.66 --share pub --root "slenk_\\FA_ROOT"')
        print('  2) 用环境变量：$env:SMB_HOST="10.118.1.66"; $env:SMB_SHARE="pub"; $env:SMB_ROOT="slenk_\\FA_ROOT"')
        return 2

    st = SmbStorage(host=a.host, share=a.share, root=a.root,
                    user=a.user, password=a.password, domain=a.domain or None)
    print("目标：", st.root_unc())
    print("健康检查：", st.health_check())

    d_rel = st.draft_rel(999999, 1)
    f_rel = st.final_rel("2026-10-08", "1F01", "B20261008A", "耐压工位",
                         st.now_ts(), "00660301", 1)
    body = ("storage ok @ %s\n" % _dt.datetime.now().isoformat(timespec="seconds")).encode("utf-8")

    st.write_bytes(d_rel, body)
    print("写草稿 OK：", d_rel)
    st.move(d_rel, f_rel)
    print("移动→正式 OK：", f_rel)
    got = st.read_bytes(f_rel)
    print("读回校验：", "一致 ✅" if got == body else "不一致 ❌")
    st.remove(f_rel)
    print("清理 OK：", f_rel)
    print("（提醒：正式上线请用专用服务账号，勿长期依赖匿名写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())