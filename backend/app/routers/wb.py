"""WB 参数查询路由（阶段 6 · 模块②）。

- 需登录；`?batch=` 或 `?bom=` 二选一（支持逗号 / 换行 / 分号 / 顿号 / 空格分隔的多个）。
- 多批次**并发**查询：单条耗时不再线性叠加，整体在预算时间内返回，避免前端 30s 超时。
- 单条失败逐条标注（ok=false + error），不遮蔽其他条目。
- 数据源不可用 → 503「数据源未配置，请联系管理员」。

为什么改成并发（原“无结果返回”的根因）
------------------------------------------------
`wb_mail.mes_api.fetch_fields()` 单个批次内部要串联调 MID(解析BOM) → 白平衡(TIOT)
→ MID(BOM) → ODF → 料单分页(内置超时 45s、含重试) 多个上游接口，单批次实测数秒~十余秒。
旧实现按 `for key in keys` **串行**调用，N 个批次的墙钟时间 ≈ 单批次 × N，很容易超过前端
的 `timeout: 30000`（http.ts）；一旦超时，前端 `catch { result.value = null }` 会把结果
置空且**不弹任何提示**（axios 超时无 HTTP status，走不到拦截器报错分支），于是表现为
“多批次查询没有任何返回”。
本模块把逐批次调用放进线程池并发执行，并在整体预算（默认 60s，小于前端 120s）内收敛：
- 正常情况：总耗时 ≈ 最慢的单批次耗时；
- 极端情况：超出预算的批次标记为“查询超时”并返回，绝不再拖到前端超时。
"""
from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait as _futures_wait

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import get_current_user
from ..models import User
from ..schemas import WbQueryResponse, WbResult
from ..services.wb_source import HttpSource, MockSource, WbUnavailable, resolve_source

router = APIRouter(prefix="/api/wb", tags=["wb"])
log = logging.getLogger("app.wb")

# 分隔符：英文/中文逗号、顿号、分号，以及所有空白（空格 / Tab / 换行）。
# 用户从 Excel 一列复制批次号时，最常见的分隔是「空格」或「换行」；旧实现只认
# 逗号/换行，整列会被当成一个批次号去查 → 查不到。这里一并支持。
_SPLIT = re.compile(r"[,，、;；\s]+")

# 并发度与整体预算（可用环境变量覆盖）。默认值保证在 30s 前端超时内返回。
#   WB_QUERY_CONCURRENCY     并发查询线程数，默认 6
#   WB_QUERY_BUDGET_SECONDS  单次请求整体预算秒数，默认 60（须 < 前端 axios timeout）
try:
    _MAX_WORKERS = max(1, int(os.environ.get("WB_QUERY_CONCURRENCY", "6")))
except ValueError:
    _MAX_WORKERS = 6
try:
    _BUDGET_SECONDS = max(1.0, float(os.environ.get("WB_QUERY_BUDGET_SECONDS", "60")))
except ValueError:
    _BUDGET_SECONDS = 60.0


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
    """切分查询关键字，并对输入去重（保持首次出现顺序）。"""
    seen: set[str] = set()
    keys: list[str] = []
    for k in _SPLIT.split(raw or ""):
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def _query_one(fn, key: str) -> WbResult:
    """查询单个关键字：异常逐条标注，绝不向外抛。"""
    started = time.monotonic()
    try:
        fields = fn(key)
        elapsed = time.monotonic() - started
        log.info("WB 查询成功 key=%s 字段数=%d 耗时=%.2fs", key, len(fields), elapsed)
        return WbResult(key=key, ok=True, fields=fields)
    except Exception as exc:  # noqa: BLE001  单条失败不遮蔽其他
        elapsed = time.monotonic() - started
        log.warning("WB 查询失败 key=%s 耗时=%.2fs: %s", key, elapsed, exc)
        return WbResult(key=key, ok=False, error=str(exc))


def _pick(done_fut, key: str) -> WbResult:
    """取已完成 Future 的结果，兜底异常。"""
    try:
        return done_fut.result()
    except Exception as exc:  # noqa: BLE001
        return WbResult(key=key, ok=False, error=f"查询异常：{type(exc).__name__}: {exc}")


def _query_concurrent(fn, keys: list[str]) -> list[WbResult]:
    """并发查询多个关键字，按输入顺序返回；超预算的条目标记为超时。"""
    workers = max(1, min(_MAX_WORKERS, len(keys)))
    started = time.monotonic()
    results: list[WbResult | None] = [None] * len(keys)
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wb-query")
    try:
        future_to_idx = {executor.submit(_query_one, fn, key): i for i, key in enumerate(keys)}
        done, pending = _futures_wait(set(future_to_idx), timeout=_BUDGET_SECONDS)
        for fut in done:
            i = future_to_idx[fut]
            results[i] = _pick(fut, keys[i])
        for fut in pending:
            fut.cancel()
            i = future_to_idx[fut]
            results[i] = WbResult(
                key=keys[i], ok=False,
                error="查询超时（超过 %.0f 秒未返回），请减少批次数量或稍后重试" % _BUDGET_SECONDS)
    finally:
        # 关键：不能在退出时 join 未完成的线程，否则预算形同虚设（会一直等到全部查完）。
        # 未完成的批次留给后台线程自然结束，本次请求按预算返回。
        executor.shutdown(wait=False, cancel_futures=True)
    log.info("WB 并发查询：%d 个关键字 并发度=%d 总耗时=%.2fs",
             len(keys), workers, time.monotonic() - started)
    return [r if r is not None else WbResult(key=keys[i], ok=False, error="未执行")
            for i, r in enumerate(results)]


@router.get("/query", response_model=WbQueryResponse)
def query(
    batch: str | None = Query(None, description="批次号，多个用逗号/换行/空格分隔"),
    bom: str | None = Query(None, description="BOM，多个用逗号/换行/空格分隔"),
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

    if len(keys) == 1:
        results = [_query_one(fn, keys[0])]
    else:
        results = _query_concurrent(fn, keys)

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
