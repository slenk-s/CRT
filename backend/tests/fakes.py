"""测试用内存存储替身：只实现路由/存储层用到的接口，避免依赖内网 SMB。"""
from __future__ import annotations

import io
from contextlib import contextmanager

from app.services.storage import StorageError


class FakeStorage:
    """内存文件系统替身。"""

    def __init__(self, root: str = "slenk_\\FA_ROOT") -> None:
        self.root = root
        self.files: dict[str, bytes] = {}
        self.removed: list[str] = []

    # ---- 路径构建（与 SmbStorage 保持一致的形状） ----
    def draft_rel(self, changeover_id, item_id, ext="jpg"):
        return f"{self.root}\\{'_draft'}\\{changeover_id}\\{item_id}.{ext}"

    def final_rel(self, date, line, batch, station, ts, emp_id, ver, ext="jpg"):
        return f"{self.root}\\{date}\\{line}\\{batch}\\{station}\\{ts}_{emp_id}_v{ver}.{ext}"

    @staticmethod
    def now_ts():
        return "120000"

    # ---- 读写 ----
    def write_bytes(self, rel, data):
        self.files[rel] = bytes(data)
        return len(data)

    def read_bytes(self, rel):
        if rel not in self.files:
            raise StorageError(f"文件不存在：{rel}")
        return self.files[rel]

    def remove(self, rel):
        if rel not in self.files:
            raise StorageError(f"文件不存在：{rel}")
        del self.files[rel]
        self.removed.append(rel)

    def exists(self, rel):
        return rel in self.files

    def reachable(self):
        return True

    def move(self, src_rel, dst_rel):
        if src_rel not in self.files:
            raise StorageError(f"源文件不存在：{src_rel}")
        self.files[dst_rel] = self.files.pop(src_rel)

    def open_stream(self, rel):
        if rel not in self.files:
            raise StorageError(f"文件不存在：{rel}")
        data = self.files[rel]

        @contextmanager
        def _cm():
            yield io.BytesIO(data)

        return _cm()


class BrokenSmbStorage:
    """模拟 SMB 完全不可用：所有 IO 均抛 StorageError，用于离线降级测试。

    `calls` 记录被调用的方法名（用于断言"确实尝试过写 SMB 才降级"）。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _broken(self, method: str, *a, **kw):
        self.calls.append(method)
        raise StorageError(f"SMB 不可用（模拟离线）：{method}")

    def write_bytes(self, rel, data):
        return self._broken("write_bytes", rel, data)

    def read_bytes(self, rel):
        return self._broken("read_bytes", rel)

    def move(self, src, dst):
        return self._broken("move", src, dst)

    def remove(self, rel):
        return self._broken("remove", rel)

    def makedirs(self, rel):
        return self._broken("makedirs", rel)

    def listdir(self, rel=None):
        return self._broken("listdir", rel)

    def exists(self, rel):
        return False

    def reachable(self):
        self.calls.append("reachable")
        return False

    def open_stream(self, rel):
        return self._broken("open_stream", rel)
