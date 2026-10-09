"""审计日志 helper（关键写操作留痕）。"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ..models import AuditLog


def log(db: Session, *, emp_id: str, action: str, target: str = "", detail: object = "") -> None:
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    db.add(AuditLog(emp_id=emp_id, action=action, target=target, detail=detail))