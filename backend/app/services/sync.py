"""后台同步服务：本地临时照片 → SMB。

SMB 不可用（离线）时上传落到本地临时目录（synced=0），本服务按
固定间隔扫描 pending 记录，在 SMB 恢复后搬运到共享盘并回填路径。
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from typing import Optional

from .. import config
from ..db import SessionLocal
from ..models import CoItemPhoto
from .storage import LocalStorage, SmbStorage, StorageError

log = logging.getLogger("sync")

_stop: threading.Event = threading.Event()
_thread: Optional[threading.Thread] = None

# ---- 实时连通性状态（供 /api/health 与前端状态条轮询）----
# 探测放到后台线程：SMB 不通时一次连接超时可能长达十几秒，
# 绝不能让 /api/health 的请求阻塞在网络上。接口只读缓存，永远瞬时返回。
_STATUS_REFRESH = 20.0
_status_stop: threading.Event = threading.Event()
_status_thread: Optional[threading.Thread] = None
_status_lock = threading.Lock()
_status_cache: dict = {"ok": False, "message": "尚未检查", "checked_at": ""}


def _new_local() -> LocalStorage:
    return LocalStorage(config.LOCAL_PHOTO_DIR)


def _now_ts() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _public_status() -> dict:
    return {"ok": _status_cache["ok"], "message": _status_cache["message"],
            "checked_at": _status_cache["checked_at"]}


def _set_status(ok: bool, message: str) -> dict:
    with _status_lock:
        _status_cache["ok"] = ok
        _status_cache["message"] = message
        _status_cache["checked_at"] = _now_ts()
        return _public_status()


def _probe_smb() -> tuple[bool, str]:
    if not (config.SMB_HOST and config.SMB_SHARE):
        return False, "SMB 未配置，照片仅保存在本地"
    try:
        smb = SmbStorage()
    except StorageError as exc:
        return False, f"SMB 不可用：{exc}"
    if smb.reachable():
        return True, "SMB 共享盘可用"
    return False, "SMB 不可用（离线）"


def _probe_and_set() -> dict:
    try:
        ok, message = _probe_smb()
    except Exception as exc:  # noqa: BLE001  探测失败不应影响服务
        ok, message = False, f"SMB 状态检测异常：{type(exc).__name__}"
    return _set_status(ok, message)


def smb_status(force: bool = False) -> dict:
    """SMB 连通性快照：{"ok", "message", "checked_at"}。

    默认只读缓存（瞬时返回）；force=True 立刻探测一次，供测试与手动刷新。
    `checked_at` 为空表示尚未完成首次探测。
    """
    if force:
        return _probe_and_set()
    with _status_lock:
        return _public_status()


def _status_loop() -> None:
    log.info("SMB 状态探测线程启动（间隔 %ds）", _STATUS_REFRESH)
    while not _status_stop.is_set():
        _probe_and_set()
        _status_stop.wait(_STATUS_REFRESH)


def start_status_loop() -> None:
    global _status_thread
    if _status_thread is not None and _status_thread.is_alive():
        return
    _status_stop.clear()
    _status_thread = threading.Thread(target=_status_loop, daemon=True, name="sync-smb-status")
    _status_thread.start()


def stop_status_loop() -> None:
    global _status_thread
    _status_stop.set()
    if _status_thread is not None:
        _status_thread.join(timeout=5)
        _status_thread = None


def _sync_once() -> int:
    """单次同步：把所有 synced=0 的照片搬到 SMB，返回成功数。"""
    if not (config.SMB_HOST and config.SMB_SHARE):
        return 0
    db = SessionLocal()
    local = _new_local()
    ok = 0
    try:
        rows = db.query(CoItemPhoto).filter(CoItemPhoto.synced == 0).all()
        if not rows:
            return 0
        try:
            smb = SmbStorage()
        except StorageError as exc:
            log.info("SMB 仍不可用，跳过本轮：%s", exc)
            _set_status(False, f"SMB 不可用：{exc}")
            return 0
        for r in rows:
            if r.synced == 1:
                continue
            try:
                if not local.exists(r.rel_path):
                    log.warning("本地文件已丢失：%s (id=%d)", r.rel_path, r.id)
                    r.synced = 1  # 标记跳过，避免反复重试
                    db.commit()
                    continue
                data = local.read_bytes(r.rel_path)
                smb.write_bytes(r.rel_path, data)
                r.synced = 1
                _set_status(True, "SMB 共享盘可用")
                # rel_path 保持不变（本地和 SMB 的相对路径结构一致）
                db.commit()
                ok += 1
                log.info("已同步 photo id=%d → %s", r.id, r.rel_path)
                try:
                    local.remove(r.rel_path)
                except StorageError:
                    pass
            except StorageError as exc:
                log.warning("同步 photo id=%d 失败：%s", r.id, exc)
                _set_status(False, f"SMB 不可用：{exc}")
                break  # SMB 又挂了，停止本轮
            except Exception:
                db.rollback()
                log.exception("同步 photo id=%d 异常", r.id)
    finally:
        db.close()
    return ok


def _loop() -> None:
    interval = max(5, config.LOCAL_PHOTO_SYNC_INTERVAL)
    log.info("同步服务启动（间隔 %ds，本地目录 %s）", interval, config.LOCAL_PHOTO_DIR)
    while not _stop.is_set():
        try:
            n = _sync_once()
            if n:
                log.info("本轮同步 %d 张照片", n)
        except Exception:
            log.exception("同步循环异常")
        _stop.wait(interval)


def start_sync_service() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="sync-local-to-smb")
    _thread.start()


def stop_sync_service() -> None:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
        _thread = None


def pending_count() -> int:
    """当前待同步数量（供 /api/health 使用）。"""
    db = SessionLocal()
    try:
        return db.query(CoItemPhoto).filter(CoItemPhoto.synced == 0).count()
    finally:
        db.close()
