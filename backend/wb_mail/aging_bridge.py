"""wb_mail v6 SMB 计划取数桥接。

优化点：
- 对 aging.fetch_plans 返回值做防御性校验（files 可能为空或缺 key）
- 明确区分"当天无排产文件"和"SMB连接失败"两种场景
- 添加耗时日志，便于排查瓶颈
"""
from __future__ import annotations

import importlib.util
import os
import time
from typing import Callable

from wb_mail import config as C

log = C.log


def load():
    """从配置路径惰性加载自带的 smb_plan 模块。"""
    if not C.AGING_FETCHER or not os.path.isfile(C.AGING_FETCHER):
        raise ImportError(f"SMB 计划模块不存在: {C.AGING_FETCHER}")
    spec = importlib.util.spec_from_file_location(
        "aging_smb_plan_fetcher", C.AGING_FETCHER)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 aging fetcher: {C.AGING_FETCHER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_config(aging, interactive: bool = False):
    """从环境变量/交互读取 SMBConfig（口令仅内存）。"""
    return aging.SMBConfig.from_env(interactive=interactive)


def make_plan_fetch(aging, cfg, allow_recent: bool = True,
                    lookback_days: int = 5) -> Callable:
    """返回 plan_fetch(workshop, date, out_dir) -> (path, matched_date, degraded)。

    默认（allow_recent=True）在目标日无干净版计划时，向过去回退 lookback_days
    （默认 5）日内的最近一个干净版计划，并把 degraded 与真实计划文件日期透传给
    邮件标题与汇总——降级必须显式标注，绝不静默冒充当天计划。allow_recent=False
    （日报入口的 --strict-plan）恢复严格模式：无计划直接抛 PlanNotFound，绝不回退。
    """

    SMBError = aging.SMBError
    PlanNotFound = getattr(aging, "PlanNotFound", SMBError)

    def _attempt(workshop, d, out_dir):
        t0 = time.time()
        extra = ({"allow_recent": True, "lookback_days": lookback_days}
                 if allow_recent else {})
        try:
            r = aging.fetch_plans(d.strftime("%Y-%m-%d"), out_dir,
                                  config=cfg, only=[workshop], interactive=False, **extra)
        except PlanNotFound:
            log.warning("%s %s 无干净版计划%s", workshop, d,
                        "（已开启回退）" if allow_recent else "（未开启回退，直接失败）")
            raise
        elapsed = time.time() - t0
        log.info("SMB取数 %s %s 耗时%.1fs", workshop, d, elapsed)

        files = r.get("files") if isinstance(r, dict) else None
        if not files:
            raise SMBError(f"{workshop} {d} 无计划文件返回")
        f = files[0]
        path = f.get("path")
        if not path:
            raise SMBError(f"{workshop} {d} 文件路径缺失: {f}")
        degraded = bool(f.get("degraded"))
        matched = f.get("matched_date", d.strftime("%Y-%m-%d"))
        if degraded:
            log.warning("%s %s 已降级回退，实际使用 %s 的计划文件，邮件将标注（计划:%s）",
                        workshop, d, matched, matched)
        return (path, matched, degraded)

    def plan_fetch(workshop: str, date, out_dir: str):
        return _attempt(workshop, date, out_dir)

    return plan_fetch
