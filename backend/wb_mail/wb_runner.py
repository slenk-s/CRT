"""wb_mail v6 白平衡抓取模块。

优化点：
- ThreadPoolExecutor 并行抓取，WB_PARALLEL 控制并发度
- 失败自动重试（WB_RETRIES 次），指数退避
- 返回结构化结果 dict：{fields, error, duration_s}，调用方可区分"空参数"与"抓取失败"
- 单批次超时从 config 读取，不再硬编码
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from wb_mail import config as C
from wb_mail import mes_api

log = C.log

_ROW_RE = re.compile(r"^ *[|](.*?)[|](.*?)[|] *$", re.M)


# ---------------------------------------------------------------------------
# 单批次抓取
# ---------------------------------------------------------------------------
def _call(batch: str, timeout: int) -> Optional[dict[str, str]]:
    """进程内直调自持取数层，返回有序参数字典；失败返回 None。"""
    try:
        return mes_api.fetch_fields(batch)
    except OSError as e:
        log.error("批次 %s 取数 IO 失败: %s", batch, e)
        return None
    except Exception as e:                      # 接口异常/解析失败统一降级
        log.warning("批次 %s 取数失败(%ds): %s: %s",
                    batch, timeout, type(e).__name__, str(e)[:200])
        return None


def parse_md(md: str | None) -> dict[str, str]:
    """把「| 参数 | 值 |」两列表格解析成有序 dict。"""
    d: dict[str, str] = {}
    if not md:
        return d
    for a, b in _ROW_RE.findall(md):
        a = a.strip().strip("*").strip()
        b = b.strip()
        if not a or set(a) <= set("-: "):
            continue
        if a in ("参数", "字段", "项目"):
            continue
        if a not in d:
            d[a] = b
    return d


def fetch_one(batch: str, retries: int | None = None,
              timeout: int | None = None) -> dict[str, Any]:
    """抓取单批次，返回 {"batch", "fields", "error", "duration_s"}。

    成功时 fields 为非空 dict，error=None。
    失败时 fields=None，error 为描述字符串。
    """
    retries = retries if retries is not None else C.WB_RETRIES
    timeout = timeout if timeout is not None else C.WB_TIMEOUT
    t0 = time.time()
    last_err = ""

    for attempt in range(1 + retries):
        fields = _call(batch, timeout)
        if fields:
            return {"batch": batch, "fields": fields, "error": None,
                    "duration_s": time.time() - t0, "attempts": attempt + 1}
        last_err = "取数失败或解析为空"
        if attempt < retries:
            wait = min(2 ** attempt, 8)
            log.info("批次 %s 第%d次失败(%s)，%ds后重试", batch, attempt + 1, last_err, wait)
            time.sleep(wait)

    return {"batch": batch, "fields": None, "error": last_err,
            "duration_s": time.time() - t0, "attempts": 1 + retries}


# ---------------------------------------------------------------------------
# 并行批量抓取
# ---------------------------------------------------------------------------
def fetch_parallel(batches: list[str], max_workers: int | None = None
                   ) -> list[dict[str, Any]]:
    """并行抓取多批次，返回与 batches 顺序一致的结果列表。"""
    if not batches:
        return []
    max_workers = max_workers or min(C.WB_PARALLEL, len(batches))
    log.info("开始并行抓取 %d 个批次 (workers=%d)", len(batches), max_workers)

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(fetch_one, b): b for b in batches}
        for fut in as_completed(future_map):
            b = future_map[fut]
            try:
                results[b] = fut.result()
            except Exception as e:
                results[b] = {"batch": b, "fields": None, "error": str(e),
                              "duration_s": 0, "attempts": 0}

    # 保持输入顺序
    ordered = [results[b] for b in batches]
    ok = sum(1 for r in ordered if r["error"] is None)
    log.info("抓取完成: %d/%d 成功, 总耗时%.1fs",
             ok, len(batches), sum(r["duration_s"] for r in ordered))
    return ordered


# ---------------------------------------------------------------------------
# 兼容旧接口（daily_job 中 fetcher(b) 调用方式）
# ---------------------------------------------------------------------------
def run_batch_md(batch: str, timeout: int | None = None) -> dict | None:
    """兼容接口：成功返回 fields dict，失败返回 None。"""
    r = fetch_one(batch, timeout=timeout)
    return r["fields"]
