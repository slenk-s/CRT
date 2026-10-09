"""管理端路由（阶段 3.4 · 仅 admin）：字典（线体/工位/检查项）与用户管理。

约定：
- 字典「停用/启用」用 active 标记，影响新建转产可选范围；
- 字典「删除」按钮为物理删除，用于移除字典项本身；已有转产历史记录保留；
- 所有变更写 audit_log；
- 重复唯一键返回 409；已删除字典项可按同名重新创建。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import DictCheckItem, DictLine, DictStation, User
from ..schemas import (
    CheckItemAdminOut,
    CheckItemCreate,
    CheckItemUpdate,
    LineAdminOut,
    LineCreate,
    LineUpdate,
    StationAdminOut,
    StationCreate,
    StationUpdate,
    UserAdminOut,
    UserCreate,
    UserUpdate,
)
from ..security import hash_password
from ..services.audit import log as audit

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------------------------------------------------------------- 线体
@router.get("/lines", response_model=list[LineAdminOut])
def list_lines(db: Session = Depends(get_db)):
    """管理端列表：含已停用（active=0）。"""
    return (db.query(DictLine)
              .order_by(DictLine.sort, DictLine.id)
              .all())


@router.post("/lines", response_model=LineAdminOut, status_code=201)
def create_line(body: LineCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    line = body.line.strip()
    workshop = body.workshop.strip()
    row = db.query(DictLine).filter(DictLine.line == line).first()
    if row:
        if row.active:
            raise HTTPException(status.HTTP_409_CONFLICT, f"线体已存在：{line}")
        # 复活软删行
        row.workshop, row.active = workshop, 1
        if body.sort:
            row.sort = body.sort
        action = "admin.line.reactivate"
    else:
        row = DictLine(workshop=workshop, line=line, sort=body.sort, active=1)
        db.add(row)
        action = "admin.line.create"
    db.flush()
    audit(db, emp_id=admin.emp_id, action=action, target=f"line:{row.id}",
          detail={"workshop": workshop, "line": line})
    db.commit()
    return row


@router.put("/lines/{line_id}", response_model=LineAdminOut)
def update_line(line_id: int, body: LineUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    row = db.get(DictLine, line_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线体不存在")
    if body.line is not None:
        line = body.line.strip()
        if line != row.line:
            dup = db.query(DictLine).filter(DictLine.line == line, DictLine.id != row.id).first()
            if dup:
                raise HTTPException(status.HTTP_409_CONFLICT, f"线体号已被占用：{line}")
            row.line = line
    if body.workshop is not None:
        row.workshop = body.workshop.strip()
    if body.sort is not None:
        row.sort = body.sort
    if body.active is not None:
        row.active = body.active
    audit(db, emp_id=admin.emp_id, action="admin.line.update", target=f"line:{row.id}",
          detail=body.model_dump(exclude_none=True))
    db.commit()
    return row


@router.delete("/lines/{line_id}")
def delete_line(line_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    """物理删除线体：已有转产历史记录保留；线体本身从字典中移除。"""
    row = db.get(DictLine, line_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "线体不存在")
    target = f"line:{row.id}"
    detail = {"workshop": row.workshop, "line": row.line}
    audit(db, emp_id=admin.emp_id, action="admin.line.delete", target=target,
          detail=detail)
    db.delete(row)
    db.commit()
    return {"ok": True, "line": row.line}


@router.post("/lines/import")
def import_lines(body: dict, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    """批量导入线体：粘贴多行「车间<分隔>线体」文本（分隔符支持 Tab / 中英文逗号 / 空白）。

    请求体：{"text": "一车间,1F01\\n二车间,2F01"}（也兼容 {"rows": [[车间, 线体], ...]}）
    """
    rows: list[tuple[str, str]] = []
    if isinstance(body.get("rows"), list):
        for r in body["rows"]:
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                rows.append((str(r[0]).strip(), str(r[1]).strip()))
    text = body.get("text") or ""
    for raw in str(text).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p for p in __import__("re").split(r"[,，\t;；]+|\s{1,}", raw) if p.strip()]
        if len(parts) < 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"无法解析行（应为「车间,线体」）：{raw}")
        rows.append((parts[0].strip(), parts[1].strip()))
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有可导入的数据")

    existing = {r.line: r for r in db.query(DictLine).all()}
    added, reactivated, skipped = 0, 0, 0
    for workshop, line in rows:
        row = existing.get(line)
        if row:
            if row.active:
                skipped += 1
                continue
            row.workshop, row.active = workshop, 1
            reactivated += 1
        else:
            db.add(DictLine(workshop=workshop, line=line, sort=(added + reactivated + 1) * 10, active=1))
            added += 1
    audit(db, emp_id=admin.emp_id, action="admin.line.import",
          detail={"added": added, "reactivated": reactivated, "skipped": skipped})
    db.commit()
    return {"ok": True, "added": added, "reactivated": reactivated, "skipped": skipped}


# ---------------------------------------------------------------- 工位
@router.get("/stations", response_model=list[StationAdminOut])
def list_stations(db: Session = Depends(get_db)):
    return db.query(DictStation).order_by(DictStation.sort, DictStation.id).all()


@router.post("/stations", response_model=StationAdminOut, status_code=201)
def create_station(body: StationCreate, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    station = body.station.strip()
    row = db.query(DictStation).filter(DictStation.station == station).first()
    if row:
        if row.active:
            raise HTTPException(status.HTTP_409_CONFLICT, f"工位已存在：{station}")
        row.active, row.sort = 1, body.sort or row.sort
        action = "admin.station.reactivate"
    else:
        row = DictStation(station=station, sort=body.sort, active=1)
        db.add(row)
        action = "admin.station.create"
    db.flush()
    audit(db, emp_id=admin.emp_id, action=action, target=f"station:{row.id}",
          detail={"station": station})
    db.commit()
    return row


@router.put("/stations/{station_id}", response_model=StationAdminOut)
def update_station(station_id: int, body: StationUpdate, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    row = db.get(DictStation, station_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "工位不存在")
    if body.station is not None:
        station = body.station.strip()
        if station != row.station:
            dup = db.query(DictStation).filter(DictStation.station == station,
                                               DictStation.id != row.id).first()
            if dup:
                raise HTTPException(status.HTTP_409_CONFLICT, f"工位名已被占用：{station}")
            row.station = station
    if body.sort is not None:
        row.sort = body.sort
    if body.active is not None:
        row.active = body.active
    audit(db, emp_id=admin.emp_id, action="admin.station.update", target=f"station:{row.id}",
          detail=body.model_dump(exclude_none=True))
    db.commit()
    return row


@router.delete("/stations/{station_id}")
def delete_station(station_id: int, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    """物理删除工位：已有转产版本记录保留；工位本身从字典中移除。"""
    row = db.get(DictStation, station_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "工位不存在")
    target = f"station:{row.id}"
    detail = {"station": row.station}
    audit(db, emp_id=admin.emp_id, action="admin.station.delete", target=target,
          detail=detail)
    db.delete(row)
    db.commit()
    return {"ok": True, "station": row.station}


# ---------------------------------------------------------------- 检查项
@router.get("/check-items", response_model=list[CheckItemAdminOut])
def list_check_items(station: str | None = None, db: Session = Depends(get_db)):
    q = db.query(DictCheckItem)
    if station:
        q = q.filter(DictCheckItem.station == station)
    return q.order_by(DictCheckItem.station, DictCheckItem.sort, DictCheckItem.id).all()


@router.post("/check-items", response_model=CheckItemAdminOut, status_code=201)
def create_check_item(body: CheckItemCreate, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    station, item = body.station.strip(), body.item.strip()
    if not db.query(DictStation).filter(DictStation.station == station,
                                        DictStation.active == 1).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"工位不存在或已停用：{station}")
    row = (db.query(DictCheckItem)
             .filter(DictCheckItem.station == station, DictCheckItem.item == item)
             .first())
    if row:
        if row.active:
            raise HTTPException(status.HTTP_409_CONFLICT, f"检查项已存在：{station}/{item}")
        row.active, row.sort = 1, body.sort
        action = "admin.checkitem.reactivate"
    else:
        row = DictCheckItem(station=station, item=item, sort=body.sort, active=1)
        db.add(row)
        action = "admin.checkitem.create"
    db.flush()
    audit(db, emp_id=admin.emp_id, action=action, target=f"checkitem:{row.id}",
          detail={"station": station, "item": item})
    db.commit()
    return row


@router.put("/check-items/{item_id}", response_model=CheckItemAdminOut)
def update_check_item(item_id: int, body: CheckItemUpdate, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    row = db.get(DictCheckItem, item_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "检查项不存在")
    if body.station is not None:
        row.station = body.station.strip()
    if body.item is not None:
        item = body.item.strip()
        if item != row.item:
            dup = (db.query(DictCheckItem)
                     .filter(DictCheckItem.station == row.station, DictCheckItem.item == item,
                             DictCheckItem.id != row.id)
                     .first())
            if dup:
                raise HTTPException(status.HTTP_409_CONFLICT, f"检查项已存在：{item}")
            row.item = item
    if body.sort is not None:
        row.sort = body.sort
    if body.active is not None:
        row.active = body.active
    audit(db, emp_id=admin.emp_id, action="admin.checkitem.update", target=f"checkitem:{row.id}",
          detail=body.model_dump(exclude_none=True))
    db.commit()
    return row


@router.delete("/check-items/{item_id}")
def delete_check_item(item_id: int, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    """物理删除检查项：已有转产版本记录保留；检查项本身从字典中移除。"""
    row = db.get(DictCheckItem, item_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "检查项不存在")
    target = f"checkitem:{row.id}"
    detail = {"station": row.station, "item": row.item}
    audit(db, emp_id=admin.emp_id, action="admin.checkitem.delete", target=target,
          detail=detail)
    db.delete(row)
    db.commit()
    return {"ok": True, "item": row.item}


# ---------------------------------------------------------------- 用户
@router.get("/users", response_model=list[UserAdminOut])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).order_by(User.emp_id).all()


@router.post("/users", response_model=UserAdminOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    emp_id = body.emp_id.strip()
    if db.get(User, emp_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"工号已存在：{emp_id}")
    user = User(emp_id=emp_id, name=body.name.strip(),
                password_hash=hash_password(body.password),
                role=body.role, active=1, must_change_password=1)   # 首次登录强制改密
    db.add(user)
    audit(db, emp_id=admin.emp_id, action="admin.user.create", target=f"user:{emp_id}",
          detail={"role": body.role})
    db.commit()
    return user


@router.put("/users/{emp_id}", response_model=UserAdminOut)
def update_user(emp_id: str, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    user = db.get(User, emp_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    # 自保护：不能停用/降级自己
    if user.emp_id == admin.emp_id and (body.active == 0 or (body.role and body.role != "admin")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用或降级当前登录账号")
    if body.name is not None:
        user.name = body.name.strip()
    if body.role is not None:
        user.role = body.role
    if body.active is not None:
        user.active = body.active
    if body.password:
        user.password_hash = hash_password(body.password)
        user.must_change_password = 1     # 重置口令后强制改密
    audit(db, emp_id=admin.emp_id, action="admin.user.update", target=f"user:{emp_id}",
          detail={k: v for k, v in body.model_dump(exclude_none=True).items() if k != "password"})
    db.commit()
    return user