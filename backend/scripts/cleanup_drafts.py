"""草稿清理（维护任务）。

未提交草稿默认保留 `DRAFT_TTL_DAYS`(7) 天：超期则删除会话 + 条目 + 草稿区照片。
**正式记录（submitted）永不自动删除。**

用法（在 backend 目录下执行）：
    python scripts/cleanup_drafts.py                 # 按 DRAFT_TTL_DAYS 清理
    python scripts/cleanup_drafts.py --days 3        # 覆盖保留天数
    python scripts/cleanup_drafts.py --dry-run       # 只打印不删除

建议用 systemd timer（见 scripts/co-maintenance.timer）每日执行。
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 便于直接运行

from app import config, db                      # noqa: E402
from app.models import Changeover, CoItem      # noqa: E402
from app.services.audit import log as audit    # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="清理超期未提交草稿")
    ap.add_argument("--days", type=int, default=config.DRAFT_TTL_DAYS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    db.init_db()
    cutoff = (dt.datetime.now() - dt.timedelta(days=max(0, args.days))).strftime("%Y-%m-%d %H:%M:%S")

    storage = None
    try:
        from app.services.storage import SmbStorage

        storage = SmbStorage()
    except Exception as exc:  # noqa: BLE001  存储不可用时仍清理数据库记录
        print(f"[警告] 存储不可用，跳过草稿文件清理：{type(exc).__name__}: {exc}")

    removed_co = removed_item = removed_file = 0
    failed_file: list[str] = []

    with db.SessionLocal() as session:
        rows = (
            session.query(Changeover)
            .filter(Changeover.status == "draft", Changeover.created_at < cutoff)
            .all()
        )
        for co in rows:
            items = session.query(CoItem).filter(CoItem.changeover_id == co.id).all()
            if not args.dry_run:
                for it in items:
                    if it.draft_rel_path and storage is not None:
                        try:
                            storage.remove(it.draft_rel_path)
                            removed_file += 1
                        except Exception as exc:  # noqa: BLE001
                            failed_file.append(f"{it.draft_rel_path}: {exc}")
                    session.delete(it)
                audit(session, emp_id="system", action="cleanup.draft", target=f"co:{co.id}",
                      detail={"line": co.line, "batch": co.batch, "created_at": co.created_at,
                              "days": args.days})
                session.delete(co)
            removed_item += len(items)
            removed_co += 1
            print(f"{'[预演] ' if args.dry_run else ''}清理草稿 id={co.id} "
                  f"{co.shot_date} {co.line} / {co.batch}（条目 {len(items)}）")
        if not args.dry_run:
            session.commit()

    print(f"\n完成：会话 {removed_co} 个，条目 {removed_item} 个，草稿文件 {removed_file} 个"
          f"{'（预演，未落库）' if args.dry_run else ''}")
    if failed_file:
        print(f"[警告] {len(failed_file)} 个草稿文件删除失败（记录已清理）：")
        for f in failed_file[:10]:
            print("   -", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
