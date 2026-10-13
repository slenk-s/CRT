"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---- 认证 ----
class LoginRequest(BaseModel):
    emp_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserOut(BaseModel):
    emp_id: str
    name: str
    role: str
    must_change_password: int = 0
    workshop: str = ""          # 所属车间；空串 = 不限定（展示全部线体）

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, description="新口令至少 6 位")


class WorkshopUpdate(BaseModel):
    """设置所属车间；空串表示不限定（展示全部线体）。"""
    workshop: str = Field("", max_length=32)


# ---- 字典 ----
class DictLineItem(BaseModel):
    id: int
    workshop: str
    line: str
    sort: int

    model_config = {"from_attributes": True}


class DictStationItem(BaseModel):
    id: int
    station: str
    sort: int

    model_config = {"from_attributes": True}


class CheckItemOut(BaseModel):
    id: int
    station: str = ""
    item: str
    sort: int

    model_config = {"from_attributes": True}


class DictLinesResponse(BaseModel):
    items: list[DictLineItem]
    by_workshop: dict[str, list[str]]


# ---- 转产会话（草稿链路）----
class ChangeoverCreate(BaseModel):
    line: str = Field(..., min_length=1, max_length=30)
    batch: str = Field(..., min_length=1, max_length=64)
    shot_date: str | None = Field(None, description="YYYY-MM-DD，缺省=今天")
    note: str = ""


class ChangeoverPatch(BaseModel):
    batch: str | None = Field(None, min_length=1, max_length=64)
    note: str | None = None


class ItemCreate(BaseModel):
    station: str = Field(..., min_length=1, max_length=64)


class ItemPatch(BaseModel):
    check_result: str | None = Field(None, description="勾选结果 JSON 字符串")
    remark: str | None = None


class ItemCorrect(BaseModel):
    """提交后更正条目（生成新版本）。"""
    check_result: str | None = Field(None, description="勾选结果 JSON 字符串；缺省=沿用上一版")
    remark: str | None = Field(None, description="备注；缺省=沿用上一版")
    edit_note: str = Field("", description="更正说明")


class ItemPhotoOut(BaseModel):
    """条目下的一张照片（草稿或正式版通用）。"""
    seq: int
    rel_path: str = ""
    name: str = ""
    size: int = 0
    synced: int = 1          # 0=本地待同步, 1=SMB
    uploader_emp_id: str = ""
    uploader_name: str = ""
    created_at: str = ""
    url: str | None = None   # /api/changeover/items/{id}/photos/{seq}


class ItemOut(BaseModel):
    id: int
    station: str
    station_sort: int = 0
    current_ver: int
    has_draft_photo: bool
    item_status: str = "unrecorded"
    draft_check_result: str = ""
    draft_remark: str = ""
    draft_size: int = 0
    draft_updated_at: str | None = None
    updated_at: str
    photo_url: str | None = None          # 兼容旧前端的第一张照片链接
    draft_photos: list[ItemPhotoOut] = []     # 全量照片（含待同步标记）
    has_photo_pending_sync: bool = False      # 是否有照片尚在本地待同步


class ChangeoverOut(BaseModel):
    id: int
    shot_date: str
    workshop: str
    line: str
    batch: str
    status: str
    uploader_emp_id: str
    uploader_name: str
    created_at: str
    submitted_at: str | None = None
    updated_at: str
    item_total: int = 0
    item_with_photo: int = 0


class ChangeoverDetail(ChangeoverOut):
    items: list[ItemOut] = []


class ChangeoverPage(BaseModel):
    total: int
    page: int
    size: int
    items: list[ChangeoverOut]


# ---- 版本 & 提交 ----
class VersionOut(BaseModel):
    ver: int
    photo_rel_path: str = ""
    photo_name: str = ""
    file_size: int = 0
    check_result: str = ""
    remark: str = ""
    edit_note: str = ""
    uploader_emp_id: str
    uploader_name: str
    created_at: str
    photo_url: str | None = None


class SubmitItemResult(BaseModel):
    item_id: int
    station: str
    ok: bool
    reason: str = ""


class SubmitResult(BaseModel):
    ok: bool
    changeover_id: int
    status: str
    versions_created: int = 0
    no_photo_items: int = 0
    failures: list[SubmitItemResult] = []
    submitted_at: str | None = None


# ---- 管理端（阶段 3.4 · 仅 admin）----
class LineAdminOut(BaseModel):
    id: int
    workshop: str
    line: str
    sort: int
    active: int

    model_config = {"from_attributes": True}


class LineCreate(BaseModel):
    workshop: str = Field(..., min_length=1, max_length=32)
    line: str = Field(..., min_length=1, max_length=30)
    sort: int = 0


class LineUpdate(BaseModel):
    workshop: str | None = Field(None, min_length=1, max_length=32)
    line: str | None = Field(None, min_length=1, max_length=30)
    sort: int | None = None
    active: int | None = Field(None, ge=0, le=1)


class StationAdminOut(BaseModel):
    id: int
    station: str
    sort: int
    active: int

    model_config = {"from_attributes": True}


class StationCreate(BaseModel):
    station: str = Field(..., min_length=1, max_length=64)
    sort: int = 0


class StationUpdate(BaseModel):
    station: str | None = Field(None, min_length=1, max_length=64)
    sort: int | None = None
    active: int | None = Field(None, ge=0, le=1)


class CheckItemAdminOut(BaseModel):
    id: int
    station: str
    item: str
    sort: int
    active: int

    model_config = {"from_attributes": True}


class CheckItemCreate(BaseModel):
    station: str = Field(..., min_length=1, max_length=64)
    item: str = Field(..., min_length=1, max_length=128)
    sort: int = 0


class CheckItemUpdate(BaseModel):
    station: str | None = Field(None, min_length=1, max_length=64)
    item: str | None = Field(None, min_length=1, max_length=128)
    sort: int | None = None
    active: int | None = Field(None, ge=0, le=1)


class UserAdminOut(BaseModel):
    emp_id: str
    name: str
    role: str
    active: int
    must_change_password: int
    created_at: str

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    emp_id: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=6, description="初始口令至少 6 位")
    role: str = Field("line", pattern="^(line|admin)$")


class UserUpdate(BaseModel):
    emp_id: str | None = Field(None, min_length=1, max_length=32, description="新工号（改名）")
    name: str | None = Field(None, min_length=1, max_length=64)
    role: str | None = Field(None, pattern="^(line|admin)$")
    active: int | None = Field(None, ge=0, le=1)
    password: str | None = Field(None, min_length=6, description="重置口令（≥6 位）")


# ---- WB 参数查询（阶段 6 · 模块②）----
class WbResult(BaseModel):
    key: str
    ok: bool
    error: str = ""
    fields: dict[str, str] = {}


class WbQueryResponse(BaseModel):
    mode: str
    source: str = ""
    results: list[WbResult] = []