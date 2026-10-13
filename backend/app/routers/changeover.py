"""转产会话路由（阶段 3.2–3.3 ＋ 阶段 4：统一提交 / 版本化纠错 / 正式图代理）。

设计要点：
- 会话状态：draft（可自由增删改、可传草稿照片）→ submitted（统一提交后会话级写操作锁定）。
- 草稿照片写 `_draft/{changeover_id}/{item_id}.{ext}`，数据库只存**共享内相对路径**。
- 提交：把草稿照片 move 到正式区（`日期/线体/批次/工位/HHMMSS_工号_v1.ext`），生成 v1 版本。
- 纠错：提交后 PUT 更正 / 重传照片 → 生成新版本（ver+1），旧版本文件与记录都保留。
- 记录只允许本人或管理员修改；所有关键写操作写 audit_log。
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import json as _json
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import ensure_owner_or_admin, get_current_user, get_storage
from ..models import Changeover, CoItem, CoItemPhoto, CoItemVersion, DictLine, DictStation, User
from ..schemas import (
    ChangeoverCreate,
    ChangeoverDetail,
    ChangeoverOut,
    ChangeoverPage,
    ChangeoverPatch,
    ItemCorrect,
    ItemCreate,
    ItemOut,
    ItemPatch,
    ItemPhotoOut,
    SubmitItemResult,
    SubmitResult,
    VersionOut,
)
from ..services.audit import log as audit
from ..services import sync as sync_svc
from ..services.storage import LocalStorage, SmbStorage, StorageError, photo_display_name, sanitize_segment

# 测试覆盖点：注入 FakeStorage 等替身
_test_smb_storage = None  # type: ignore[assignment]
_test_local_storage = None  # type: ignore[assignment]

router = APIRouter(prefix="/api/changeover", tags=["changeover"])

_ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
_MAGIC = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"RIFF", "webp"),          # RIFF....WEBP
)
_MEDIA_TYPE = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


# ---------------------------------------------------------------- helpers
def _now_str() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return _dt.date.today().isoformat()


def _parse_date(s: str) -> str:
    try:
        return _dt.date.fromisoformat(s).isoformat()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"日期格式应为 YYYY-MM-DD：{s}") from exc


def _line_workshop(db: Session, line: str) -> str:
    row = db.query(DictLine).filter(DictLine.line == line, DictLine.active == 1).first()
    if not row:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"线体不存在或已停用：{line}")
    return row.workshop


def _station_sort_map(db: Session) -> dict[str, int]:
    return {r.station: r.sort for r in db.query(DictStation).all()}


def parse_checked_names(check_result: str | None) -> set[str]:
    if not check_result:
        return set()
    try:
        obj = _json.loads(check_result)
        if isinstance(obj, dict):
            return {k for k, v in obj.items() if v}
        if isinstance(obj, list):
            return set(obj)
    except (ValueError, TypeError):
        pass
    return set()


def derive_item_status(has_photo: bool, check_result: str | None, remark: str | None) -> str:
    if parse_checked_names(check_result) or (remark and remark.strip()) or has_photo:
        return "recorded"
    return "unrecorded"


def _get_co(db: Session, co_id: int) -> Changeover:
    co = db.get(Changeover, co_id)
    if not co:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "转产记录不存在")
    return co


def _get_item(db: Session, item_id: int) -> CoItem:
    item = db.get(CoItem, item_id)
    if not item or item.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "工位条目不存在")
    return item


def _require_draft(co: Changeover) -> None:
    if co.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "该转产已提交，不能再修改草稿；如需更正请走纠错流程")


def _latest_version(db: Session, item_id: int) -> CoItemVersion | None:
    return (db.query(CoItemVersion)
              .filter(CoItemVersion.item_id == item_id)
              .order_by(CoItemVersion.ver.desc())
              .first())


def _latest_versions(db: Session, item_ids: list[int]) -> dict[int, CoItemVersion]:
    """一次性取多个条目的最新版本（item_id → 最高 ver）。"""
    if not item_ids:
        return {}
    rows = (db.query(CoItemVersion)
              .filter(CoItemVersion.item_id.in_(item_ids))
              .order_by(CoItemVersion.item_id, CoItemVersion.ver.desc())
              .all())
    out: dict[int, CoItemVersion] = {}
    for r in rows:
        out.setdefault(r.item_id, r)   # 首次出现即最高版本
    return out


def _latest_version_path(db: Session, item_id: int) -> str:
    row = _latest_version(db, item_id)
    return row.photo_rel_path if row else ""


def _item_photos_out(db: Session, item: CoItem) -> list[ItemPhotoOut]:
    """条目下所有照片（按 seq 升序）。"""
    rows = (db.query(CoItemPhoto)
              .filter(CoItemPhoto.item_id == item.id)
              .order_by(CoItemPhoto.seq.asc())
              .all())
    return [
        ItemPhotoOut(
            seq=r.seq, rel_path=r.rel_path, name=r.name, size=r.size or 0,
            synced=r.synced if r.synced is not None else 1,
            uploader_emp_id=r.uploader_emp_id or "", uploader_name=r.uploader_name or "",
            created_at=r.created_at or "",
            url=f"/api/changeover/items/{item.id}/photos/{r.seq}",
        )
        for r in rows
    ]


def _next_seq(db: Session, item_id: int) -> int:
    """条目内下一个照片序号。"""
    row = (db.query(CoItemPhoto)
              .filter(CoItemPhoto.item_id == item_id)
              .order_by(CoItemPhoto.seq.desc())
              .first())
    return ((row.seq if row else 0) or 0) + 1


def _build_rel(*parts: str) -> str:
    """按 SMB 相对路径规则拼接（含 SMB_ROOT 前缀）。"""
    segs: list[str] = []
    if config.SMB_ROOT:
        segs.append(config.SMB_ROOT.replace("/", "\\").strip("\\"))
    for p in parts:
        seg = sanitize_segment(p).replace("/", "\\")
        if seg:
            segs.append(seg)
    return "\\".join(segs)


def _draft_rel(co_id: int, item_id: int, name: str) -> str:
    """草稿相对路径：_draft/{co_id}/{item_id}/{name}"""
    return _build_rel("_draft", str(co_id), str(item_id), name)


def _final_rel(date: str, line: str, batch: str, station: str, name: str) -> str:
    """正式归档相对路径：{date}/{line}/{batch}/{station}/{name}"""
    return _build_rel(date, line, batch, station, name)


def _local_storage() -> LocalStorage:
    if _test_local_storage is not None:
        return _test_local_storage
    return LocalStorage(config.LOCAL_PHOTO_DIR)


def _smb_storage_or_none() -> SmbStorage | None:
    if _test_smb_storage is not None:
        return _test_smb_storage
    if not (config.SMB_HOST and config.SMB_SHARE):
        return None
    try:
        return SmbStorage()
    except StorageError:
        return None


def _smb_skip_write() -> bool:
    """是否跳过 SMB、直接写本地。

    只有后台探测**明确判定在线**时才去写 SMB；尚未探测（检测中/尚未检查）一律按离线
    处理——否则每次上传都要先白等一次连接超时（离线时约 5s），界面看着像卡死了。
    判定离线时本地 rel_path 与共享盘一致，后台同步服务会照原样补推。

    测试替身（_test_smb_storage）优先于缓存判定，避免真实探测结果影响替身用例。
    """
    if _test_smb_storage is not None:
        return False
    return not sync_svc.smb_status().get("ok")


def _write_photo_fallback(rel: str, data: bytes) -> tuple[int, str]:
    """写照片（SMB 优先，失败降级到本地）。返回 (synced, actual_rel)。

    - synced=1：文件已写入 SMB
    - synced=0：文件写入本地目录，后台自动同步
    """
    smb = None if _smb_skip_write() else _smb_storage_or_none()
    if smb is not None:
        try:
            smb.write_bytes(rel, data)
            return 1, rel
        except StorageError:
            pass
    local = _local_storage()
    local.write_bytes(rel, data)
    return 0, rel


def _item_out(db: Session, item: CoItem, co: Changeover, sorts: dict[str, int],
              submitted: bool, latest: CoItemVersion | None = None) -> ItemOut:
    """条目展示：草稿态读草稿字段；已提交态读最新版本 + 全量照片列表。"""
    photos = _item_photos_out(db, item)
    has_photo = bool(photos)
    if submitted:
        check = (latest.check_result if latest else "") or ""
        remark = (latest.remark if latest else "") or ""
        size = (latest.file_size if latest else 0) or 0
        upd = latest.created_at if latest else item.updated_at
        photo_url = (f"/api/changeover/items/{item.id}/photo?ver={item.current_ver}"
                     if has_photo else None)
    else:
        check = item.draft_check_result or ""
        remark = item.draft_remark or ""
        size = item.draft_size or 0
        upd = item.draft_updated_at
        photo_url = f"/api/changeover/items/{item.id}/photo" if has_photo else None
    pending_sync = any(p.synced == 0 for p in photos)
    return ItemOut(
        id=item.id,
        station=item.station,
        station_sort=sorts.get(item.station, 10_000),
        current_ver=item.current_ver,
        has_draft_photo=has_photo,
        item_status=derive_item_status(has_photo, check, remark),
        draft_check_result=check,
        draft_remark=remark,
        draft_size=size,
        draft_updated_at=upd,
        updated_at=item.updated_at,
        photo_url=photo_url,
        draft_photos=photos,
        has_photo_pending_sync=pending_sync,
    )


def _co_out(co: Changeover, total: int = 0, with_photo: int = 0) -> ChangeoverOut:
    return ChangeoverOut(
        id=co.id, shot_date=co.shot_date, workshop=co.workshop, line=co.line, batch=co.batch,
        status=co.status, uploader_emp_id=co.uploader_emp_id, uploader_name=co.uploader_name,
        created_at=co.created_at, submitted_at=co.submitted_at, updated_at=co.updated_at,
        item_total=total, item_with_photo=with_photo,
    )


def _counts(db: Session, ids: list[int]) -> dict[int, tuple[int, int]]:
    """会话 → (条目数, 有照片条目数)；已提交会话以最新版本是否含照片为准。"""
    if not ids:
        return {}
    rows = (db.query(CoItem.id, CoItem.changeover_id)
              .filter(CoItem.changeover_id.in_(ids), CoItem.is_deleted == 0)
              .all())
    if not rows:
        return {}
    latest = _latest_versions(db, [r[0] for r in rows])
    # 查询所有条目的照片记录
    photo_rows = (db.query(CoItemPhoto.item_id)
                    .filter(CoItemPhoto.item_id.in_([r[0] for r in rows]))
                    .all())
    items_with_photo = {r[0] for r in photo_rows}
    agg: dict[int, tuple[int, int]] = {}
    for item_id, co_id in rows:
        total, with_photo = agg.get(co_id, (0, 0))
        total += 1
        ver = latest.get(item_id)
        if item_id in items_with_photo or (ver and ver.photo_rel_path):
            with_photo += 1
        agg[co_id] = (total, with_photo)
    return agg


def _sniff_ext(head: bytes, filename: str) -> str:
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            if ext == "webp" and head[8:12] != b"WEBP":
                continue
            return ext
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext in _ALLOWED_EXT:
        return ext
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg / png / webp 图片")


async def _read_image(file: UploadFile) -> tuple[bytes, str]:
    """读取并校验上传图片：返回 (bytes, ext)。"""
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "空文件")
    limit = config.MAX_IMAGE_MB * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                            f"图片超过 {config.MAX_IMAGE_MB} MB 上限")
    return data, _sniff_ext(data[:16], file.filename or "")


# ---------------------------------------------------------------- 会话
@router.post("", response_model=ChangeoverDetail, status_code=201)
def create_changeover(
    body: ChangeoverCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新建转产会话（草稿态）。同一「日期+线体+批次」唯一。"""
    shot_date = _parse_date(body.shot_date) if body.shot_date else _today()
    batch = body.batch.strip()
    workshop = _line_workshop(db, body.line.strip())

    exists = (db.query(Changeover)
                .filter(Changeover.shot_date == shot_date,
                        Changeover.line == body.line.strip(),
                        Changeover.batch == batch)
                .first())
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"该日期+线体+批次已存在转产记录（id={exists.id}，状态={exists.status}）")

    co = Changeover(shot_date=shot_date, workshop=workshop, line=body.line.strip(), batch=batch,
                    status="draft", uploader_emp_id=user.emp_id, uploader_name=user.name)
    db.add(co)
    db.flush()
    audit(db, emp_id=user.emp_id, action="changeover.create", target=f"co:{co.id}",
          detail={"date": shot_date, "line": co.line, "batch": batch, "note": body.note})
    db.commit()
    return ChangeoverDetail(**_co_out(co).model_dump(), items=[])


@router.get("", response_model=ChangeoverPage)
def list_changeovers(
    status_: str | None = Query(None, alias="status"),
    line: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    mine: bool = False,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Changeover)
    if status_:
        q = q.filter(Changeover.status == status_)
    if line:
        q = q.filter(Changeover.line == line)
    if date_from:
        q = q.filter(Changeover.shot_date >= _parse_date(date_from))
    if date_to:
        q = q.filter(Changeover.shot_date <= _parse_date(date_to))
    if keyword:
        q = q.filter(Changeover.batch.contains(keyword.strip()))
    if mine:
        q = q.filter(Changeover.uploader_emp_id == user.emp_id)

    total = q.count()
    rows = q.order_by(Changeover.id.desc()).offset((page - 1) * size).limit(size).all()
    counts = _counts(db, [r.id for r in rows])
    return ChangeoverPage(
        total=total, page=page, size=size,
        items=[_co_out(r, *counts.get(r.id, (0, 0))) for r in rows],
    )


@router.get("/export.csv")
def export_changeovers_csv(
    status_: str | None = Query(None, alias="status"),
    line: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    keyword: str | None = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出 CSV（阶段 5）：筛选条件同列表，**按工位条目（最新版）一行**，UTF-8 BOM。"""
    q = db.query(Changeover)
    if status_:
        q = q.filter(Changeover.status == status_)
    if line:
        q = q.filter(Changeover.line == line)
    if date_from:
        q = q.filter(Changeover.shot_date >= _parse_date(date_from))
    if date_to:
        q = q.filter(Changeover.shot_date <= _parse_date(date_to))
    if keyword:
        q = q.filter(Changeover.batch.contains(keyword.strip()))
    if mine:
        q = q.filter(Changeover.uploader_emp_id == user.emp_id)

    cos = q.order_by(Changeover.id.desc()).limit(10000).all()
    co_ids = [c.id for c in cos]
    items = (db.query(CoItem)
               .filter(CoItem.changeover_id.in_(co_ids), CoItem.is_deleted == 0)
               .all()) if co_ids else []
    latest = _latest_versions(db, [i.id for i in items])
    by_co: dict[int, list[CoItem]] = {}
    for it in items:
        by_co.setdefault(it.changeover_id, []).append(it)

    buf = io.StringIO()
    buf.write("\ufeff")   # UTF-8 BOM：Excel 打开中文不乱码
    w = csv.writer(buf)
    w.writerow(["日期", "车间", "线体", "批次", "工位", "版本", "勾选结果", "备注",
                "文件名", "路径", "上传人工号", "上传人", "上传时间"])
    for co in cos:
        for it in sorted(by_co.get(co.id, []), key=lambda x: x.id):
            if co.status == "submitted":
                v = latest.get(it.id)
                row = [co.shot_date, co.workshop, co.line, co.batch, it.station,
                       f"v{it.current_ver}" if v else "",
                       (v.check_result if v else "") or "",
                       (v.remark if v else "") or "",
                       (v.photo_name if v else "") or "",
                       (v.photo_rel_path if v else "") or "",
                       (v.uploader_emp_id if v else co.uploader_emp_id),
                       (v.uploader_name if v else co.uploader_name),
                       (v.created_at if v else "") or ""]
            else:
                row = [co.shot_date, co.workshop, co.line, co.batch, it.station, "草稿",
                       it.draft_check_result or "", it.draft_remark or "",
                       it.draft_name or "", it.draft_rel_path or "",
                       co.uploader_emp_id, co.uploader_name, it.draft_updated_at or ""]
            w.writerow(row)

    data = buf.getvalue().encode("utf-8")
    fname = quote(f"转产记录导出_{_today()}.csv")
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=changeover.csv; filename*=UTF-8''{fname}"},
    )


@router.get("/{co_id}", response_model=ChangeoverDetail)
def get_changeover(
    co_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    co = _get_co(db, co_id)
    items = (db.query(CoItem)
               .filter(CoItem.changeover_id == co_id, CoItem.is_deleted == 0)
               .all())
    sorts = _station_sort_map(db)
    items.sort(key=lambda i: (sorts.get(i.station, 10_000), i.id))
    submitted = co.status == "submitted"
    latest = _latest_versions(db, [i.id for i in items]) if submitted else {}
    outs = [_item_out(db, i, co, sorts, submitted, latest.get(i.id)) for i in items]
    total = len(outs)
    with_photo = sum(1 for o in outs if o.has_draft_photo)
    return ChangeoverDetail(**_co_out(co, total, with_photo).model_dump(), items=outs)


@router.patch("/{co_id}", response_model=ChangeoverOut)
def patch_changeover(
    co_id: int,
    body: ChangeoverPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """草稿态可改批次号；备注仅留痕。"""
    co = _get_co(db, co_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    _require_draft(co)

    if body.batch is not None:
        batch = body.batch.strip()
        dup = (db.query(Changeover)
                 .filter(Changeover.shot_date == co.shot_date, Changeover.line == co.line,
                         Changeover.batch == batch, Changeover.id != co.id)
                 .first())
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, f"批次号已存在（id={dup.id}）")
        co.batch = batch
        audit(db, emp_id=user.emp_id, action="changeover.patch", target=f"co:{co.id}",
              detail={"batch": batch})
    if body.note:
        audit(db, emp_id=user.emp_id, action="changeover.note", target=f"co:{co.id}",
              detail={"note": body.note})
    db.commit()
    counts = _counts(db, [co.id]).get(co.id, (0, 0))
    return _co_out(co, *counts)


@router.delete("/{co_id}")
def delete_changeover(
    co_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    storage: SmbStorage = Depends(get_storage),
):
    """删除草稿会话：清草稿照片 + 删条目与会话（已提交记录不可删）。"""
    co = _get_co(db, co_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    _require_draft(co)

    items = db.query(CoItem).filter(CoItem.changeover_id == co_id).all()
    removed, failed = 0, []
    for it in items:
        photos = db.query(CoItemPhoto).filter(CoItemPhoto.item_id == it.id).all()
        for p in photos:
            try:
                if p.synced == 1:
                    storage.remove(p.rel_path)
                    removed += 1
                else:
                    local = _local_storage()
                    if local.exists(p.rel_path):
                        local.remove(p.rel_path)
                        removed += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{p.rel_path}: {exc}")
            db.delete(p)
        db.delete(it)
    audit(db, emp_id=user.emp_id, action="changeover.delete", target=f"co:{co.id}",
          detail={"line": co.line, "batch": co.batch, "files_removed": removed,
                  "file_errors": failed})
    db.delete(co)
    db.commit()
    return {"ok": True, "files_removed": removed, "file_errors": failed}


# ---------------------------------------------------------------- 统一提交（阶段 4）
@router.post("/{co_id}/submit", response_model=SubmitResult)
def submit_changeover(
    co_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """统一提交：草稿照片 → 正式归档（v1）→ 会话置 submitted。

    - 每条目的照片按 seq 升序遍历
    - 草稿照片（synced=1，在共享盘上）move 到正式区
    - 本地照片（synced=0，离线上传）仅在本地 move 到正式目录，synced 保持 0，
      等 SMB 恢复后由后台同步服务推送到共享盘
    - 未传照片的条目：允许（部分提交），仍生成 v1
    - 条目内任一张照片无法归档：整条失败并回报（已搬的文件会搬回），其余照常转正
    - 全部条目都失败：不提交（保持草稿），返回 ok=False

    SMB 离线时，synced=1 的照片位于共享盘上、本地没有副本，无法归档，
    该条目会整体失败——不会出现「同一条目一半转正一半留在草稿」的状态。
    """
    co = _get_co(db, co_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    if co.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "该转产已提交，请勿重复提交")

    items = (db.query(CoItem)
               .filter(CoItem.changeover_id == co_id, CoItem.is_deleted == 0)
               .order_by(CoItem.id)
               .all())
    if not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该转产没有任何工位条目，无法提交")

    created = 0
    no_photo = 0
    failures: list[SubmitItemResult] = []

    # 整场只探测一次 SMB 可达性：离线时每次探测都要等满连接超时，
    # 逐张照片探测会把一次提交拖成分钟级。
    _probed: list[bool] = []

    def _smb_online() -> bool:
        if not _probed:
            smb = _smb_storage_or_none()
            _probed.append(bool(smb and smb.reachable()))
        return _probed[0]

    def _relocate(p: CoItemPhoto, dst: str) -> None:
        """把照片文件搬到 dst（同盘）。不校验存在性，调用方负责预检。"""
        if p.synced == 1:
            smb = _smb_storage_or_none()
            if not smb:
                raise StorageError("SMB 不可用（离线）")
            if dst != p.rel_path:
                smb.move(p.rel_path, dst)
        else:
            # 离线照片只在本地搬：synced 保持 0，SMB 恢复后由后台同步服务
            # 按 rel_path 原样推送到共享盘（本地与共享盘路径结构一致）。
            _local_storage().move(p.rel_path, dst)

    for it in items:
        photos = (db.query(CoItemPhoto)
                    .filter(CoItemPhoto.item_id == it.id)
                    .order_by(CoItemPhoto.seq.asc())
                    .all())

        # 先整条预检再搬运：否则可能出现「前几张已进正式区、后面失败」，
        # 留下条目仍是草稿、文件却已在正式区的错位状态。
        plan: list[tuple[CoItemPhoto, str]] = []
        reason = ""
        for p in photos:
            dst = _final_rel(co.shot_date, co.line, co.batch, it.station, p.name)
            if p.synced == 1:
                if not _smb_online():
                    reason = "归档失败：SMB 不可用（离线），该照片在共享盘上，暂时无法归档"
                    break
                if not _smb_storage_or_none().exists(p.rel_path):
                    reason = "归档失败：草稿照片在共享盘上缺失"
                    break
            elif not _local_storage().exists(p.rel_path):
                reason = "归档失败：本地草稿照片文件缺失"
                break
            plan.append((p, dst))
        if reason:
            failures.append(SubmitItemResult(item_id=it.id, station=it.station, ok=False,
                                             reason=reason))
            continue

        archived: list[CoItemPhoto] = []
        # 已搬走的照片，失败时逐张搬回，保证条目整体要么全转正、要么维持草稿
        moved: list[tuple[CoItemPhoto, str]] = []
        try:
            for p, dst in plan:
                prev = p.rel_path
                _relocate(p, dst)
                p.rel_path = dst
                moved.append((p, prev))
                archived.append(p)
        except StorageError as exc:
            for p, prev in reversed(moved):
                try:
                    _relocate(p, prev)
                except StorageError:
                    pass  # 搬不回去也只能先还原记录，避免指向不存在的新路径
                p.rel_path = prev
            failures.append(SubmitItemResult(item_id=it.id, station=it.station, ok=False,
                                             reason=f"归档失败：{exc}"))
            continue

        first = archived[0] if archived else None
        rel_path = first.rel_path if first else ""
        photo_name = first.name if first else ""
        file_size = sum(p.size for p in archived)

        db.add(CoItemVersion(
            item_id=it.id, ver=1, photo_rel_path=rel_path,
            photo_name=photo_name, file_size=file_size,
            check_result=it.draft_check_result or "", remark=it.draft_remark or "",
            edit_note="", uploader_emp_id=user.emp_id, uploader_name=user.name,
        ))
        it.current_ver = 1
        it.draft_check_result = ""
        it.draft_remark = ""
        it.draft_updated_at = None
        if not archived:
            no_photo += 1
        created += 1

    if created == 0:
        db.rollback()
        return SubmitResult(ok=False, changeover_id=co.id, status="draft",
                            versions_created=0, no_photo_items=no_photo, failures=failures)

    co.status = "submitted"
    co.submitted_at = _now_str()
    audit(db, emp_id=user.emp_id, action="changeover.submit", target=f"co:{co.id}",
          detail={"versions_created": created, "no_photo_items": no_photo,
                  "failures": [f.model_dump() for f in failures]})
    db.commit()
    return SubmitResult(ok=True, changeover_id=co.id, status="submitted",
                        versions_created=created, no_photo_items=no_photo,
                        failures=failures, submitted_at=co.submitted_at)


@router.post("/{co_id}/items", response_model=ItemOut, status_code=201)
def add_item(
    co_id: int,
    body: ItemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    co = _get_co(db, co_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    _require_draft(co)

    station = body.station.strip()
    if not db.query(DictStation).filter(DictStation.station == station, DictStation.active == 1).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"工位不存在或已停用：{station}")

    item = (db.query(CoItem)
              .filter(CoItem.changeover_id == co_id, CoItem.station == station)
              .first())
    if item and not item.is_deleted:
        raise HTTPException(status.HTTP_409_CONFLICT, f"该工位已添加：{station}")
    if item:  # 复用软删行
        item.is_deleted = 0
    else:
        item = CoItem(changeover_id=co_id, station=station)
        db.add(item)
    db.flush()
    audit(db, emp_id=user.emp_id, action="item.add", target=f"co:{co_id}/item:{item.id}",
          detail={"station": station})
    db.commit()
    return _item_out(db, item, co, _station_sort_map(db), False)


@router.patch("/items/{item_id}", response_model=ItemOut)
def patch_item(
    item_id: int,
    body: ItemPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新**草稿**元数据：勾选结果（JSON 字符串）/ 备注。已提交请用 PUT 更正。"""
    item = _get_item(db, item_id)
    co = _get_co(db, item.changeover_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    _require_draft(co)

    if body.check_result is not None:
        try:
            _json.loads(body.check_result or "{}")
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "check_result 必须是合法 JSON") from exc
        item.draft_check_result = body.check_result
    if body.remark is not None:
        item.draft_remark = body.remark
    item.draft_updated_at = _now_str()
    audit(db, emp_id=user.emp_id, action="item.patch", target=f"item:{item.id}",
          detail={"check_result": body.check_result is not None,
                  "remark": body.remark is not None})
    db.commit()
    return _item_out(db, item, co, _station_sort_map(db), False)


@router.put("/items/{item_id}", response_model=ItemOut)
def correct_item(
    item_id: int,
    body: ItemCorrect,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """提交后更正条目（勾选/备注）→ 生成新版本（ver+1），旧版本保留。"""
    item = _get_item(db, item_id)
    co = _get_co(db, item.changeover_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    if co.status != "submitted":
        raise HTTPException(status.HTTP_409_CONFLICT, "该转产尚未提交，请直接修改草稿")

    latest = _latest_version(db, item.id)
    if not latest:
        raise HTTPException(status.HTTP_409_CONFLICT, "该条目没有可更正的版本")

    if body.check_result is not None:
        try:
            _json.loads(body.check_result or "{}")
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "check_result 必须是合法 JSON") from exc
        new_check = body.check_result
    else:
        new_check = latest.check_result
    new_remark = body.remark if body.remark is not None else latest.remark

    new_ver = item.current_ver + 1
    ver = CoItemVersion(
        item_id=item.id, ver=new_ver, photo_rel_path=latest.photo_rel_path,
        photo_name=latest.photo_name, file_size=latest.file_size,
        check_result=new_check, remark=new_remark or "",
        edit_note=body.edit_note or "更正",
        uploader_emp_id=user.emp_id, uploader_name=user.name,
    )
    db.add(ver)
    item.current_ver = new_ver
    audit(db, emp_id=user.emp_id, action="item.correct", target=f"item:{item.id}",
          detail={"ver": new_ver, "edit_note": body.edit_note})
    db.commit()
    return _item_out(db, item, co, _station_sort_map(db), True, ver)


@router.delete("/items/{item_id}")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """草稿：删条目并清草稿文件；已提交：软删（保留正式文件与版本历史）。"""
    item = _get_item(db, item_id)
    co = _get_co(db, item.changeover_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)

    files_removed = 0
    if co.status == "draft":
        photos = db.query(CoItemPhoto).filter(CoItemPhoto.item_id == item.id).all()
        for p in photos:
            try:
                if p.synced == 1:
                    smb = _smb_storage_or_none()
                    if smb and smb.exists(p.rel_path):
                        smb.remove(p.rel_path)
                        files_removed += 1
                else:
                    local = _local_storage()
                    if local.exists(p.rel_path):
                        local.remove(p.rel_path)
                        files_removed += 1
            except Exception:  # noqa: BLE001
                pass
            db.delete(p)
        item.is_deleted = 1
        audit(db, emp_id=user.emp_id, action="item.delete", target=f"item:{item.id}",
              detail={"station": item.station, "files_removed": files_removed})
    else:
        item.is_deleted = 1
        audit(db, emp_id=user.emp_id, action="item.soft_delete", target=f"item:{item.id}",
              detail={"station": item.station})
    db.commit()
    return {"ok": True, "files_removed": files_removed}


# ---------------------------------------------------------------- 照片
@router.post("/items/{item_id}/photo", response_model=ItemOut)
async def upload_item_photo(
    item_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """追加一张照片到条目（多图）。

    - 草稿态：写 _draft 区，文件名统一为 `{批次}_{工位}_{序号}.{ext}`。
    - 已提交态：写正式区 + 生成新版本（旧版本保留）。
    - SMB 不可用时自动降级到本地临时目录（synced=0），后台自动同步。
    """
    item = _get_item(db, item_id)
    co = _get_co(db, item.changeover_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)

    data, ext = await _read_image(file)
    sorts = _station_sort_map(db)
    seq = _next_seq(db, item.id)
    name = photo_display_name(co.batch, item.station, seq, ext)

    if co.status == "draft":
        rel = _draft_rel(co.id, item.id, name)
        synced, actual_rel = _write_photo_fallback(rel, data)
        photo = CoItemPhoto(
            item_id=item.id, seq=seq, rel_path=actual_rel, name=name,
            size=len(data), synced=synced,
            uploader_emp_id=user.emp_id, uploader_name=user.name,
        )
        db.add(photo)
        item.draft_updated_at = _now_str()
        audit(db, emp_id=user.emp_id, action="item.photo.upload", target=f"item:{item.id}",
              detail={"seq": seq, "path": actual_rel, "size": len(data), "synced": synced})
        db.commit()
        return _item_out(db, item, co, sorts, False)

    if co.status == "submitted":
        latest = _latest_version(db, item.id)
        if not latest:
            raise HTTPException(status.HTTP_409_CONFLICT, "该条目没有可追加的版本")
        new_ver = item.current_ver + 1
        dst = _final_rel(co.shot_date, co.line, co.batch, item.station, name)
        synced, actual_rel = _write_photo_fallback(dst, data)
        if synced == 0:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "SMB 不可用；已暂存到本地临时目录（synced=0），恢复后会自动同步",
            )
        ver = CoItemVersion(
            item_id=item.id, ver=new_ver, photo_rel_path=actual_rel,
            photo_name=name, file_size=len(data),
            check_result=latest.check_result, remark=latest.remark,
            edit_note="追加照片", uploader_emp_id=user.emp_id, uploader_name=user.name,
        )
        db.add(ver)
        photo = CoItemPhoto(
            item_id=item.id, seq=seq, rel_path=actual_rel, name=name,
            size=len(data), synced=synced,
            uploader_emp_id=user.emp_id, uploader_name=user.name,
        )
        db.add(photo)
        item.current_ver = new_ver
        audit(db, emp_id=user.emp_id, action="item.photo.append", target=f"item:{item.id}",
              detail={"seq": seq, "ver": new_ver, "path": actual_rel, "size": len(data)})
        db.commit()
        return _item_out(db, item, co, sorts, True, ver)

    raise HTTPException(status.HTTP_409_CONFLICT, "未知会话状态")


@router.delete("/items/{item_id}/photos/{seq}")
def delete_item_photo(
    item_id: int,
    seq: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除单张照片（仅草稿态可用）。"""
    item = _get_item(db, item_id)
    co = _get_co(db, item.changeover_id)
    ensure_owner_or_admin(co.uploader_emp_id, user)
    if co.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "已提交条目不能删除单张照片；如需更正请用 PUT /items/{id}")

    photo = (db.query(CoItemPhoto)
               .filter(CoItemPhoto.item_id == item.id, CoItemPhoto.seq == seq)
               .first())
    if not photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"照片不存在 (seq={seq})")

    removed = False
    err = ""
    try:
        if photo.synced == 1:
            smb = _smb_storage_or_none()
            if smb and smb.exists(photo.rel_path):
                smb.remove(photo.rel_path)
                removed = True
        else:
            local = _local_storage()
            if local.exists(photo.rel_path):
                local.remove(photo.rel_path)
                removed = True
    except StorageError as exc:
        err = str(exc)

    db.delete(photo)
    item.draft_updated_at = _now_str()
    audit(db, emp_id=user.emp_id, action="item.photo.delete", target=f"item:{item.id}",
          detail={"seq": seq, "removed": removed, "err": err})
    db.commit()
    return {"ok": True, "removed": removed, "error": err}


@router.get("/items/{item_id}/photos/{seq}")
def get_item_photo_by_seq(
    item_id: int,
    seq: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按 seq 取单张照片（草稿/正式通用）。本地降级照片也可访问。"""
    item = _get_item(db, item_id)
    photo = (db.query(CoItemPhoto)
               .filter(CoItemPhoto.item_id == item.id, CoItemPhoto.seq == seq)
               .first())
    if not photo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"照片不存在 (seq={seq})")

    rel = photo.rel_path
    if photo.synced == 0:
        storage_obj = _local_storage()
        if not storage_obj.exists(rel):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件不存在")
    else:
        storage_obj = _smb_storage_or_none()
        if not storage_obj:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "存储不可用")
        if not storage_obj.exists(rel):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件不存在（可能已被清理）")

    ext = rel.rsplit(".", 1)[-1].lower()

    def _iter():
        with storage_obj.open_stream(rel) as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type=_MEDIA_TYPE.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/items/{item_id}/photo")
def get_item_photo(
    item_id: int,
    ver: int | None = Query(None, description="指定版本号；缺省=草稿/首张优先"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """兼容旧前端：按 ver 或缺省取一张照片。本地降级照片也可访问。"""
    item = _get_item(db, item_id)

    if ver is not None:
        row = (db.query(CoItemVersion)
                 .filter(CoItemVersion.item_id == item.id, CoItemVersion.ver == ver)
                 .first())
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"版本不存在：v{ver}")
        rel = row.photo_rel_path
        if not rel:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"v{ver} 无照片")
    else:
        # 优先取首张照片（草稿或已提交的首张）
        photo = (db.query(CoItemPhoto)
                   .filter(CoItemPhoto.item_id == item.id)
                   .order_by(CoItemPhoto.seq.asc())
                   .first())
        rel = photo.rel_path if photo else ""
        if not rel:
            # 回退到版本表第一张
            latest = _latest_version(db, item.id)
            rel = latest.photo_rel_path if latest else ""

    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该条目暂无照片")

    # 判断存储位置
    storage_obj = _smb_storage_or_none()
    if storage_obj and storage_obj.exists(rel):
        pass
    else:
        local = _local_storage()
        if local.exists(rel):
            storage_obj = local
        else:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件不存在（可能已被清理）")

    ext = rel.rsplit(".", 1)[-1].lower()

    def _iter():
        with storage_obj.open_stream(rel) as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type=_MEDIA_TYPE.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "no-store"},
    )

@router.get("/items/{item_id}/versions", response_model=list[VersionOut])
def list_item_versions(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = _get_item(db, item_id)
    rows = (db.query(CoItemVersion)
              .filter(CoItemVersion.item_id == item.id)
              .order_by(CoItemVersion.ver.desc())
              .all())
    return [
        VersionOut(
            ver=r.ver, photo_rel_path=r.photo_rel_path, photo_name=r.photo_name,
            file_size=r.file_size or 0, check_result=r.check_result or "",
            remark=r.remark or "", edit_note=r.edit_note or "",
            uploader_emp_id=r.uploader_emp_id, uploader_name=r.uploader_name,
            created_at=r.created_at,
            photo_url=(f"/api/changeover/items/{item.id}/photo?ver={r.ver}"
                       if r.photo_rel_path else None),
        )
        for r in rows
    ]
