"""wb_mail v6 主编排：每日全流程。

优化点：
- 文件日志 + stdout 双通道，定时任务可事后追查
- 抓取改为并行（wb_runner.fetch_parallel），大幅缩短总耗时
- 执行报告结构化：每线体耗时、批次数、成功率，末尾输出 JSON 摘要便于回执解析
- 失败优雅降级：部分批次抓取失败仍发邮件，标注失败批次
- CLI 增加 --verbose / --log-dir / --parallel 参数
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any, Callable, Optional

from wb_mail import config as C
from wb_mail import batch_filter as bf
from wb_mail import wb_runner
from wb_mail import contacts as ct
from wb_mail import mail_assembler as ma
from wb_mail import mail_sender

log = C.log

# 向后兼容：定时任务可能直接引用 C.load_smb_credentials()
# 已在 config.py 中做别名映射


def build_emails(plan_fetch: Callable, workshop: str, date: datetime.date,
                 out_dir: str, contacts: dict,
                 parallel: int | None = None,
                 fetch_fn: Callable | None = None,
                 ahead: int = 1) -> tuple[list[dict], list[tuple]]:
    """单车间全流程：取当天计划文件 → 筛次日批次 → 并行抓WB → 路由 → 组装邮件。

    ahead: 提前天数。默认 1 = 用 date 当天的计划文件，产出 date+1 的白平衡数据，
           与老化表的"当天计划做次日数据"口径一致。

    fetch_fn: 抓取函数 (batches, parallel) -> results；None 则用真实 MES 抓取。
              dry-run 时由调用方传入 _stub_fetch 避免连 MES。
    返回 (emails, unconfigured)。
    """
    if fetch_fn is None:
        fetch_fn = wb_runner.fetch_parallel

    picked = plan_fetch(workshop, date, out_dir)
    if not picked:
        return ([], [])
    path, file_date_str, degraded = picked
    if degraded:
        log.warning("%s 目标日期无计划，已降级使用 %s 的计划文件（邮件标注（计划:%s））",
                    workshop, file_date_str, file_date_str)

    # 提前一天发送：用「当天计划文件」筛「次日排产批次」。
    # 实测 生产四车间9月19日整机计划.xlsx 属滚动计划、内含次日排产行：
    # 同一文件按 9/19 筛出 4F01=5、4F03=1，按 9/20 筛出 4F01=8、4F02=1、4F03=5。
    # 因此批次筛选与邮件标题都必须用目标日，不能用文件日期。
    target = date + datetime.timedelta(days=ahead)
    date_str = "%d月%d日" % (target.month, target.day)
    groups = bf.extract_batches(path, plan_date=target)
    if not groups:
        log.info("指定计划中无目标日期 %s 的排产批次，不回退其他日期", date_str)

    emails: list[dict] = []
    unconfigured: list[tuple] = []

    for grp in groups:
        line = grp["line"]
        to, cc = ct.resolve(contacts, workshop, line)
        if not to:
            unconfigured.append((workshop, line, len(grp["batches"])))
            continue

        # 并行抓取所有批次
        batches_list = grp["batches"]
        t0 = time.time()
        fetch_results = fetch_fn(batches_list, parallel)
        fetch_elapsed = time.time() - t0

        # 构造 batches 对列表 [(batch, fields_or_None)]
        batches_pairs = [(r["batch"], r["fields"]) for r in fetch_results]

        # 组装邮件
        msg = ma.assemble(车间=workshop, line=line, date_str=date_str,
                          degraded=degraded, plan_file_date=file_date_str,
                          batches=batches_pairs, fetch_results=fetch_results)

        ok_count = sum(1 for r in fetch_results if r["fields"])
        emails.append({
            "line": line,
            "subject": msg["subject"],
            "to": to,
            "cc": cc,
            "body": msg["body"],
            "n_batches": len(batches_pairs),
            "n_ok": ok_count,
            "total_qty": grp.get("total_qty", 0),
            "degraded": degraded,
            "plan_file_date": file_date_str,
            "fetch_elapsed": round(fetch_elapsed, 1),
        })

    return (emails, unconfigured)


def _line_summary(workshop: str, email: dict) -> dict:
    return {
        "workshop": workshop,
        "line": email["line"],
        "batches": email["n_batches"],
        "ok": email["n_ok"],
        "fetch_s": email["fetch_elapsed"],
        "to": email["to"],
        "cc": email["cc"],
    }


def _write_preview(out_dir: str, workshop: str, email: dict) -> str:
    safe_name = "".join(
        char if char.isalnum() or char in "-_" else "_"
        for char in f"{workshop}-{email['line']}"
    )
    path = os.path.join(out_dir, safe_name + ".html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(email["body"])
    return path


def _deliver(pending: list[tuple[str, dict]], dry_run: bool,
             out_dir: str, summary: dict[str, Any], out) -> None:
    for workshop, email in pending:
        line_info = _line_summary(workshop, email)
        summary["lines"].append(line_info)
        tag = "DRY" if dry_run else "SEND"
        print(f"[{tag}] {email['subject']} 批次={email['n_batches']}"
              f"(成功{email['n_ok']}) 收件={email['to']}", file=out)

        if dry_run:
            line_info["preview_path"] = _write_preview(out_dir, workshop, email)
            summary["dry"] += 1
            continue

        result = mail_sender.send(
            email["subject"], email["to"], email["cc"], email["body"]
        )
        line_info["channel"] = result.get("channel")
        line_info["body_kb"] = round((result.get("body_bytes") or 0) / 1024, 1)
        if result["ok"]:
            summary["sent"] += 1
        else:
            summary["errors"].append({
                "subject": email["subject"],
                "error_type": result.get("error_type"),
                "channel": result.get("channel"),
                "unconfirmed": bool(result.get("unconfirmed")),
                "detail": result["output"][:300],
            })


def run_once(plan_fetch: Callable, workshops, contacts: dict,
             date: Optional[datetime.date] = None,
             dry_run: bool = False,
             only: Optional[list[str]] = None,
             parallel: Optional[int] = None,
             out_dir: Optional[str] = None,
             ahead: int = 1,
             out=sys.stdout) -> dict[str, Any]:
    """执行全流程，返回结构化 summary。"""
    date = date or datetime.date.today()
    out_dir = out_dir or os.path.join(C.OUT_BASE, date.strftime("%Y%m%d"))
    os.makedirs(out_dir, exist_ok=True)

    workshop_names = list(workshops) if not isinstance(workshops, dict) else list(workshops.keys())
    if only:
        wanted = set(only)
        workshop_names = [w for w in workshop_names if w in wanted]

    # dry-run 仍抓取真实 MES 数据，只跳过最终投递，才能实际核对邮件正文。
    fetch_fn = None

    summary: dict[str, Any] = {
        "version": C.VERSION,
        "date": date.isoformat(),
        "ahead": ahead,
        "plan_for": (date + datetime.timedelta(days=ahead)).isoformat(),
        "dry_run": dry_run,
        "sent": 0, "dry": 0, "skipped": 0,
        "lines": [], "unconfigured": [], "errors": [], "degraded": [],
        "total_elapsed": 0.0,
    }
    t_start = time.time()
    pending: list[tuple[str, dict]] = []

    for workshop in workshop_names:
        t_ws = time.time()
        try:
            emails, unc = build_emails(plan_fetch, workshop, date, out_dir,
                                       contacts, parallel=parallel,
                                       fetch_fn=fetch_fn, ahead=ahead)
        except Exception as e:
            log.exception("车间 %s 处理异常", workshop)
            summary["errors"].append({"workshop": workshop, "error": str(e)})
            continue

        # 线体在名单中未配置负责人：跳过该线体、不发送，但**不阻断**其他线体。
        # 只有致命错误（车间级异常、名单整体加载失败、端点缺失）才中止整批。
        for u in unc:
            summary["unconfigured"].append({"workshop": u[0], "line": u[1],
                                            "n_batches": u[2]})
            print(f"[WARN] 未配置负责人：{u[0]} {u[1]}（{u[2]}个批次，跳过不发送）", file=out)

        for em in emails:
            if em.get("degraded"):
                summary["degraded"].append({"workshop": workshop, "line": em["line"],
                                             "plan_file_date": em.get("plan_file_date")})
        pending.extend((workshop, em) for em in emails)
        ws_elapsed = time.time() - t_ws
        log.info("车间 %s 准备完成: %d线体, %.1fs", workshop, len(emails), ws_elapsed)

    # 车间级错误不再整体中止：失败车间记入 errors 后跳过，其他已就绪车间照常投递。
    # 唯一会整体中止的是全局性致命错误（名单整体加载失败、必需端点缺失），它们在
    # live_run 中于进入本函数前就 return 了。因此这里始终投递 pending 中的就绪邮件。
    _deliver(pending, dry_run, out_dir, summary, out)

    summary["skipped"] = len(summary["unconfigured"])
    summary["total_elapsed"] = round(time.time() - t_start, 1)
    return summary


def live_run(date: Optional[datetime.date] = None,
             dry_run: bool = False,
             contacts_path: Optional[str] = None,
             only: Optional[list[str]] = None,
             parallel: Optional[int] = None,
             log_dir: Optional[str] = None,
             ahead: int = 1,
             strict_plan: bool = False,
             lookback_days: Optional[int] = None) -> dict[str, Any]:
    """真实运行入口：加载凭据 → 拉最新名单 → 连 SMB → 并行抓取 → 发邮件。"""
    C.setup_logging(log_dir=log_dir)
    C.load_credentials()

    # 端点注入：MES/白平衡/ODF/料单 地址与密钥不落包，运行时从 T盘拉取
    from wb_mail import mes_env
    mes_env.load()
    miss = mes_env.missing_required(mes_env.LIVE_REQUIRED)
    if miss:
        log.error("必需端点缺失: %s；请确认 T盘 wb-mail 下 wb_endpoints.env 可用",
                  ", ".join(miss))
        return {"sent": 0, "errors": [{"error": "端点缺失: " + ",".join(miss)}],
                "version": C.VERSION}

    # 名单：每次发送前先从 T盘拉最新（业务侧持续维护），失败才回退本地文件
    from wb_mail import contacts_pan as cp
    date = date or datetime.date.today()
    pan_dest, src = cp.fetch_contacts(os.path.join(C.OUT_BASE, "contacts"))
    if pan_dest:
        cpath = pan_dest
    elif os.environ.get("WB_ALLOW_LOCAL_CONTACTS") == "1":
        # 仅在显式开启时才允许回退，且必须 WARNING：包内副本可能已过期，
        # 用它发信等于"用旧名单还以为新名单"。
        cpath = contacts_path or C.CONTACTS_PATH
        src = "%s；已显式允许回退本地 %s（可能过期）" % (src, cpath)
        log.warning("名单回退本地，本次可能使用过期收件人: %s", cpath)
    else:
        log.error("T盘名单拉取失败且未开启 WB_ALLOW_LOCAL_CONTACTS，终止发送: %s", src)
        return {"sent": 0, "errors": [{"error": "T盘名单拉取失败: " + src}],
                "version": C.VERSION, "contacts_source": src}
    log.info("本次名单来源: %s", src)

    contacts = ct.load_contacts(cpath) if (cpath and os.path.isfile(cpath)) else {}
    if not contacts:
        log.warning("名单为空（%s），流程终止", src)
        return {"sent": 0, "errors": [{"error": "名单为空"}],
                "version": C.VERSION, "contacts_source": src}

    # SMB 取数桥接
    from wb_mail import aging_bridge
    aging = aging_bridge.load()
    cfg = aging_bridge.make_config(aging, interactive=not dry_run)
    # 计划降级：默认开启，向过去回退最多 5 天（可用 WB_PLAN_LOOKBACK_DAYS 覆盖）。
    # --strict-plan 恢复严格模式：目标日无干净版计划直接失败，绝不回退。
    lookback = (lookback_days if lookback_days is not None
                else int(os.environ.get("WB_PLAN_LOOKBACK_DAYS", "5")))
    plan_fetch = aging_bridge.make_plan_fetch(
        aging, cfg, allow_recent=not strict_plan, lookback_days=lookback)
    if strict_plan:
        log.info("已启用 --strict-plan：目标日无计划将直接失败，不回退")
    else:
        log.info("计划降级已开启：目标日无计划时向过去回退最多 %d 天", lookback)

    # 车间列表只有一份真源：assets/smb_config.json。
    workshops = list(cfg.workshops)

    res = run_once(plan_fetch, workshops, contacts, date=date,
                   dry_run=dry_run, only=only, parallel=parallel, ahead=ahead)
    res["contacts_source"] = src
    return res

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="wb_mail.daily_job",
        description="v6 每日按线体发白平衡参数邮件")
    ap.add_argument("--date", help="计划文件日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--ahead", type=int, default=1,
                    help="提前天数：用该日期的计划文件发 date+ahead 的批次数据，默认1(次日)")
    ap.add_argument("--lookback-days", type=int, default=None,
                    help="计划降级回退窗口天数(默认5，可用 WB_PLAN_LOOKBACK_DAYS 覆盖)")
    ap.add_argument("--strict-plan", action="store_true",
                    help="严格模式：目标日无干净版计划直接失败，禁止回退")
    ap.add_argument("--dry-run", action="store_true",
                    help="完整抓取并生成 HTML 预览，但不发送")
    ap.add_argument("--contacts", default=C.CONTACTS_PATH, help="名单 xlsx 路径")
    ap.add_argument("--only", action="append", help="仅处理这些车间，可多次")
    ap.add_argument("--parallel", type=int, default=None,
                    help=f"WB抓取并行度(默认{C.WB_PARALLEL})")
    ap.add_argument("--log-dir", default=None, help="日志文件输出目录")
    ap.add_argument("--verbose", "-v", action="store_true", help="DEBUG 级别日志")
    args = ap.parse_args(argv)

    if args.verbose:
        C.setup_logging(level="DEBUG")

    date = (datetime.datetime.strptime(args.date, "%Y-%m-%d").date()
            if args.date else datetime.date.today())

    s = live_run(date=date, dry_run=args.dry_run, contacts_path=args.contacts,
                 only=args.only, parallel=args.parallel, log_dir=args.log_dir,
                 ahead=args.ahead, strict_plan=args.strict_plan,
                 lookback_days=args.lookback_days)

    # 结构化摘要（方便定时任务解析回执）
    print("\n== 汇总 ==")
    print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
    return 0 if not s.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
