"""数据模型（SQLAlchemy 2.0）。

三张核心表：changeover（转产记录/会话）→ co_item（工位条目）→ co_item_version（版本）。
外加：users、dict_line、dict_station、dict_check_item、audit_log。

约定：
- 时间统一字符串 'YYYY-MM-DD HH:MM:SS'（本地时区）；
- 照片只存**共享内相对路径**（含 SMB_ROOT），不在库内存图；
- 字典删除为物理删除；字典停用使用 active=0，历史记录可追溯。
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class User(Base):
    __tablename__ = "users"
    emp_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="line")   # line | admin
    # 所属车间：空串=不限定（展示全部线体）；否则新建转产与列表筛选只展示该车间的线体
    workshop: Mapped[str] = mapped_column(String(32), default="")
    active: Mapped[int] = mapped_column(Integer, default=1)
    must_change_password: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class Changeover(Base):
    """一次转产（会话）。"""
    __tablename__ = "changeover"
    __table_args__ = (
        UniqueConstraint("shot_date", "line", "batch", name="uk_co_date_line_batch"),
        Index("idx_co_status", "status"),
        Index("idx_co_line", "line"),
        Index("idx_co_date", "shot_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shot_date: Mapped[str] = mapped_column(String(10))              # YYYY-MM-DD
    workshop: Mapped[str] = mapped_column(String(32), default="")
    line: Mapped[str] = mapped_column(String(30))
    batch: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | submitted
    uploader_emp_id: Mapped[str] = mapped_column(String(32))
    uploader_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    submitted_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class CoItem(Base):
    """工位条目（一个转产下每个工位一条）。"""
    __tablename__ = "co_item"
    __table_args__ = (
        UniqueConstraint("changeover_id", "station", name="uk_item_co_station"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changeover_id: Mapped[int] = mapped_column(ForeignKey("changeover.id"))
    station: Mapped[str] = mapped_column(String(64))
    current_ver: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[int] = mapped_column(Integer, default=0)
    # ---- 草稿态（提交前的暂存）；提交后由 co_item_version 留存历史 ----
    draft_rel_path: Mapped[str] = mapped_column(String(512), default="")
    draft_name: Mapped[str] = mapped_column(String(255), default="")
    draft_size: Mapped[int] = mapped_column(Integer, default=0)
    draft_check_result: Mapped[str] = mapped_column(Text, default="")
    draft_remark: Mapped[str] = mapped_column(Text, default="")
    draft_updated_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), default=_now)
    updated_at: Mapped[str] = mapped_column(String(32), default=_now, onupdate=_now)


class CoItemPhoto(Base):
    """条目照片（草稿 + 正式版统一表；按 seq 排序）。

    - 上传一张 = 一行；`seq` 在同一条目内从 1 递增
    - `synced=1` 表示文件在 SMB（`rel_path` 为 SMB 相对路径）
    - `synced=0` 表示文件仅在本地临时目录（SMB 离线降级），待后台同步
    - 文件名格式：`{批次}_{工位}_{序号}.{ext}`；提交归档后补 `_v{版本}`，
      替换某张时写 `_v{新版本}`（旧文件保留，版本历史要读回）
    """
    __tablename__ = "co_item_photo"
    __table_args__ = (
        UniqueConstraint("item_id", "seq", name="uk_photo_item_seq"),
        Index("idx_photo_item", "item_id"),
        Index("idx_photo_synced", "synced"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("co_item.id"))
    seq: Mapped[int] = mapped_column(Integer)                       # 1-based
    rel_path: Mapped[str] = mapped_column(String(512))              # 相对路径
    name: Mapped[str] = mapped_column(String(255))                  # 批次_工位_序号.ext
    size: Mapped[int] = mapped_column(Integer, default=0)
    synced: Mapped[int] = mapped_column(Integer, default=1)         # 1=SMB, 0=本地待同步
    uploader_emp_id: Mapped[str] = mapped_column(String(32), default="")
    uploader_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class CoItemVersion(Base):
    """工位条目版本（每次修改/重传新增一版，旧版保留）。"""
    __tablename__ = "co_item_version"
    __table_args__ = (
        UniqueConstraint("item_id", "ver", name="uk_ver_item_ver"),
        Index("idx_ver_item", "item_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("co_item.id"))
    ver: Mapped[int] = mapped_column(Integer)                       # 从 1 递增
    photo_rel_path: Mapped[str] = mapped_column(String(512))       # 共享内相对路径
    photo_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    check_result: Mapped[str] = mapped_column(Text, default="")    # 勾选结果 JSON
    remark: Mapped[str] = mapped_column(Text, default="")
    edit_note: Mapped[str] = mapped_column(Text, default="")       # 更正说明
    uploader_emp_id: Mapped[str] = mapped_column(String(32))
    uploader_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32), default=_now)


class DictLine(Base):
    __tablename__ = "dict_line"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workshop: Mapped[str] = mapped_column(String(32))
    line: Mapped[str] = mapped_column(String(30), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[int] = mapped_column(Integer, default=1)


class DictStation(Base):
    __tablename__ = "dict_station"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station: Mapped[str] = mapped_column(String(64), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[int] = mapped_column(Integer, default=1)


class DictCheckItem(Base):
    __tablename__ = "dict_check_item"
    __table_args__ = (
        UniqueConstraint("station", "item", name="uk_checkitem_station_item"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station: Mapped[str] = mapped_column(String(64))
    item: Mapped[str] = mapped_column(String(128))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[int] = mapped_column(Integer, default=1)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emp_id: Mapped[str] = mapped_column(String(32), default="")
    action: Mapped[str] = mapped_column(String(48), default="")
    target: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(String(32), default=_now)