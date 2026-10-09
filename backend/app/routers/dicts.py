"""字典路由：线体 / 工位 / 检查项。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import DictCheckItem, DictLine, DictStation
from ..schemas import CheckItemOut, DictLinesResponse, DictStationItem

router = APIRouter(prefix="/api/dict", tags=["dict"])


@router.get("/lines", response_model=DictLinesResponse)
def list_lines(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = (
        db.query(DictLine)
        .filter(DictLine.active == 1)
        .order_by(DictLine.sort, DictLine.id)
        .all()
    )
    items = [{"id": r.id, "workshop": r.workshop, "line": r.line, "sort": r.sort} for r in rows]
    by_workshop: dict[str, list[str]] = {}
    for r in rows:
        by_workshop.setdefault(r.workshop, []).append(r.line)
    return DictLinesResponse(items=items, by_workshop=by_workshop)


@router.get("/stations", response_model=list[DictStationItem])
def list_stations(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return (
        db.query(DictStation)
        .filter(DictStation.active == 1)
        .order_by(DictStation.sort, DictStation.id)
        .all()
    )


@router.get("/check-items", response_model=list[CheckItemOut])
def list_check_items(
    station: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(DictCheckItem).filter(DictCheckItem.active == 1)
    if station:
        q = q.filter(DictCheckItem.station == station)
    return q.order_by(DictCheckItem.sort, DictCheckItem.id).all()