"""启动自检（部署用）。

用法：
    cd backend && python -m app.preflight            # 人类可读报告
    cd backend && python -m app.preflight --json     # 机器可读（CI/监控）
    cd backend && python -m app.preflight --strict   # 有告警即视为失败（可放 systemd ExecStartPre）

退出码：0 = 无致命问题；1 = 存在致命项（或 --strict 下有告警）。

检查项：
  1. 配置：JWT_SECRET / SMB_* / 种子管理员
  2. 数据库：父目录可写、可建表、可读写
  3. SMB 存储：连通性（照片链路）
  4. WB 数据源：可解析（mes / http / mock / 不可用）
  5. 前端 dist：是否可托管（单端口部署）
  6. MES 端点：缺失项清单（WB 真实查询依赖）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

from . import config, db
from .models import DictLine, DictStation, User  # noqa: F401  确保模型注册

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"


def _check_config() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    rows.append(
        ("JWT_SECRET", OK if config.JWT_SECRET else FAIL,
         "已配置" if config.JWT_SECRET else "未配置：无法签发登录 token（必配）")
    )
    smb_ok = bool(config.SMB_HOST and config.SMB_SHARE)
    rows.append(
        ("SMB_HOST/SHARE", OK if smb_ok else WARN,
         f"{config.SMB_HOST or '-'} / {config.SMB_SHARE or '-'}" if smb_ok
         else "未配置：照片上传/归档将返回 503")
    )
    if smb_ok:
        rows.append(
            ("SMB 认证", OK if config.SMB_USER else WARN,
             f"服务账号 {config.SMB_USER}" if config.SMB_USER else "匿名(guest)访问，生产环境必须改专用账号")
        )
    rows.append(
        ("种子管理员", OK if config.SEED_ADMIN_EMP_ID else WARN,
         config.SEED_ADMIN_EMP_ID if config.SEED_ADMIN_EMP_ID else "未配置：仅首次建库时生效，已建库可忽略")
    )
    return rows


def _check_db() -> tuple[list[tuple[str, str, str]], dict]:
    rows: list[tuple[str, str, str]] = []
    info: dict = {}
    try:
        db.init_db()
        with db.engine.connect() as conn:
            n_line = conn.execute(text("select count(*) from dict_line")).scalar() or 0
            n_station = conn.execute(text("select count(*) from dict_station")).scalar() or 0
            n_user = conn.execute(text("select count(*) from users")).scalar() or 0
        info = {"lines": int(n_line), "stations": int(n_station), "users": int(n_user)}
        rows.append(("数据库可读写", OK, f"{config.DB_PATH}（线体 {n_line} / 工位 {n_station} / 用户 {n_user}）"))
        if int(n_line) == 0:
            rows.append(("字典种子", WARN, "线体表为空：确认已执行 seed（首次启动会自动灌入）"))
    except Exception as exc:  # noqa: BLE001
        rows.append(("数据库可读写", FAIL, f"{type(exc).__name__}: {exc}"))
    return rows, info


def _check_storage() -> list[tuple[str, str, str]]:
    if not (config.SMB_HOST and config.SMB_SHARE):
        return [("SMB 连通", WARN, "跳过：未配置 SMB_HOST/SMB_SHARE")]
    try:
        from .services.storage import SmbStorage

        st = SmbStorage().health_check()
        if st.get("ok"):
            return [("SMB 连通", OK, f"{st.get('root')}（{st.get('items')} 项）")]
        return [("SMB 连通", FAIL, str(st.get("message") or st))]
    except Exception as exc:  # noqa: BLE001
        return [("SMB 连通", FAIL, f"{type(exc).__name__}: {exc}")]


def _check_wb() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    try:
        from .services.wb_source import WbUnavailable, resolve_source

        try:
            src = resolve_source()
        except WbUnavailable as exc:
            src = None
            rows.append(("WB 数据源", WARN, f"不可用：{exc}（/api/wb/query 将返回 503）"))
        if src is not None:
            rows.append(("WB 数据源", OK, f"{type(src).__name__}（WB_SOURCE={config.WB_SOURCE}）"))
        elif config.WB_SOURCE == "mock":
            rows.append(("WB 数据源", WARN, "mock 源未启用（检查 WB_SOURCE）"))
        else:
            rows.append(("WB 数据源", WARN, "不可用：wb_mail/HTTP 端点均缺失，/api/wb/query 将返回 503"))
    except Exception as exc:  # noqa: BLE001
        rows.append(("WB 数据源", WARN, f"{type(exc).__name__}: {exc}"))

    missing = config.missing_required(config.WB_ENDPOINT_KEYS)
    rows.append(
        ("MES 端点", OK if not missing else WARN,
         "已配置" if not missing else "缺失：" + ", ".join(missing))
    )
    return rows


def _check_frontend() -> list[tuple[str, str, str]]:
    from .main import resolve_frontend_dir

    try:
        fe = resolve_frontend_dir()
    except Exception as exc:  # noqa: BLE001
        return [("前端托管", WARN, f"{type(exc).__name__}: {exc}")]
    if fe:
        return [("前端托管", OK, f"{fe}（单端口访问：http://<host>:{config.APP_PORT}/）")]
    return [("前端托管", WARN, f"未找到 {config.FRONTEND_DIST}/index.html（仅提供 API；Nginx 模式可忽略）")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="产线转产管理轻应用 · 启动自检")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="有告警即返回失败码")
    args = ap.parse_args(argv)

    rows = _check_config()
    db_rows, db_info = _check_db()
    rows += db_rows + _check_storage() + _check_wb() + _check_frontend()

    n_fail = sum(1 for _, s, _ in rows if s == FAIL)
    n_warn = sum(1 for _, s, _ in rows if s == WARN)

    if args.json:
        print(json.dumps({
            "ok": n_fail == 0,
            "fatal": n_fail,
            "warnings": n_warn,
            "app": config.APP_NAME,
            "version": config.APP_VERSION,
            "db": db_info,
            "checks": [{"name": n, "status": s, "detail": d} for n, s, d in rows],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n{config.APP_NAME} v{config.APP_VERSION} · 启动自检\n" + "-" * 66)
        for name, status, detail in rows:
            mark = {OK: "[ OK ]", WARN: "[警告]", FAIL: "[致命]"}[status]
            print(f"{mark} {name:<16} {detail}")
        print("-" * 66)
        print(f"结果：致命 {n_fail} 项，告警 {n_warn} 项")
        if n_fail:
            print("→ 存在致命项，请先修复后再启动服务。")
        elif n_warn:
            print("→ 无致命问题；告警项为功能降级提示（如照片/ WB 查询不可用）。")

    if n_fail:
        return 1
    if args.strict and n_warn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
