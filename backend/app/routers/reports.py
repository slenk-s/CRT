"""统计接口（阶段 5 · 预留框架，先返回固定结构）。"""
from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Changeover, CoItem

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/changeover")
def changeover_stats(
    days: int = 14,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """近 N 天提交量与条目量（前端折线图占位数据源）＋ 线体 Top10。"""
    days = max(1, min(days, 90))
    today = _dt.date.today()
    start = (today - _dt.timedelta(days=days - 1)).isoformat()

    rows = (db.query(Changeover.shot_date,
                     func.count(func.distinct(Changeover.id)),
                     func.count(func.distinct(CoItem.id)))
              .outerjoin(CoItem,
                         (CoItem.changeover_id == Changeover.id) & (CoItem.is_deleted == 0))
              .filter(Changeover.shot_date >= start)
              .group_by(Changeover.shot_date)
              .all())
    by_date = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in rows}

    series = []
    for i in range(days - 1, -1, -1):
        d = (today - _dt.timedelta(days=i)).isoformat()
        co_n, item_n = by_date.get(d, (0, 0))
        series.append({"date": d, "changeovers": co_n, "items": item_n})

    line_rows = (db.query(Changeover.line, func.count(Changeover.id))
                   .group_by(Changeover.line)
                   .order_by(func.count(Changeover.id).desc())
                   .limit(10)
                   .all())

    return {
        "days": days,
        "series": series,
        "by_line": [{"line": r[0], "count": int(r[1] or 0)} for r in line_rows],
    }