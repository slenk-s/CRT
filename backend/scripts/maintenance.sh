#!/usr/bin/env bash
# 备份 SQLite 元数据（在线备份，无需停服）+ 清理超期草稿。
# 由 co-maintenance.timer 每日调用，也可手动执行。
set -u

DIR=/opt/changeover
BACKUP_DIR=${BACKUP_DIR:-/opt/changeover/backups}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-30}
DB=${DB_PATH:-$DIR/backend/data/app.db}
APP_PY=${APP_PY:-$DIR/backend/.venv/bin/python}

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)

echo "==== $(date '+%F %T') 维护开始 ===="

# ---- 1. SQLite 备份 ----
if [ -f "$DB" ]; then
  TARGET="$BACKUP_DIR/app-$TS.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB" ".backup '$TARGET'" && echo "[备份] $TARGET"
  else
    cp -f "$DB" "$TARGET" && echo "[备份] $TARGET（文件拷贝；建议安装 sqlite3 以获得在线备份）"
  fi
  gzip -f "$TARGET" 2>/dev/null || true
else
  echo "[备份] 跳过：未找到数据库 $DB"
fi

# ---- 2. 超期草稿清理（正式记录永不自动删） ----
cd "$DIR/backend" || exit 1
"$APP_PY" scripts/cleanup_drafts.py || echo "[清理] 执行失败（退出码 $?）"

# ---- 3. 备份轮转 ----
find "$BACKUP_DIR" -maxdepth 1 -name 'app-*.db*' -type f -mtime "+$KEEP_DAYS" -print -delete \
  | sed 's/^/[轮转] 删除 /' || true

echo "==== $(date '+%F %T') 维护完成 ===="
