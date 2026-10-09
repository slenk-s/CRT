"""WB 参数查询路由（阶段 6 · 模块②）。

- 需登录；`?batch=` 或 `?bom=` 二选一（支持逗号/换行/分号分隔的多个）。
- 单条失败逐条标注（ok=false + error），不遮蔽其他条目。
- 数据源不可用 → 503「数据源未配置，请联系管理员」。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_current_user
from ..models import User
from ..schemas import WbQueryResponse, WbResult
from ..services.wb_source import HttpSource, MockSource, WbUnavailable, resolve_source

router = APIRouter(prefix="/api/wb", tags=["wb"])

_SPLIT = re.compile(r"[,，\n;；]+")


def get_wb_source():
    """WB 数据源依赖：不可用时返回 503（而非 500）。"""
    try:
        src = resolve_source()
    except WbUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"数据源未配置，请联系管理员（{exc}）") from exc
    if src is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "数据源未配置，请联系管理员")
    return src


def _split_keys(raw: str) -> list[str]:
    return [k.strip() for k in _SPLIT.split(raw or "") if k.strip()]


@router.get("/query", response_model=WbQueryResponse)
def query(
    batch: str | None = Query(None, description="批次号，多个用逗号/换行分隔"),
    bom: str | None = Query(None, description="BOM，多个用逗号/换行分隔"),
    user: User = Depends(get_current_user),
    source: object = Depends(get_wb_source),
):
    if bool(batch) == bool(bom):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请且仅提供 batch 或 bom 之一")

    if batch:
        keys = _split_keys(batch)
        fn = source.query_by_batch
        mode = "batch"
    else:
        keys = _split_keys(bom)
        fn = source.query_by_bom
        mode = "bom"

    if not keys:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "查询关键字为空")

    results: list[WbResult] = []
    for key in keys:
        try:
            fields = fn(key)
            results.append(WbResult(key=key, ok=True, fields=fields))
        except Exception as exc:  # noqa: BLE001  单条失败不遮蔽其他
            results.append(WbResult(key=key, ok=False, error=str(exc)))

    return WbQueryResponse(mode=mode, source=type(source).__name__, results=results)


@router.get("/status")
def wb_status(user: User = Depends(get_current_user)):
    """数据源可用性（供前端提示；不抛错）。"""
    try:
        src = resolve_source()
    except WbUnavailable:
        src = None
    return {
        "available": src is not None,
        "source": type(src).__name__ if src else None,
        "mode": "batch" if (src is not None and isinstance(src, (MockSource, HttpSource))) else "mes",
    }