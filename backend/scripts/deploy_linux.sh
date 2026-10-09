#!/usr/bin/env bash
# =============================================================================
# 产线转产管理轻应用 · Linux 一键部署（内网服务器正式态）
#
#   用法： sudo bash scripts/deploy_linux.sh [--dir /opt/changeover] [--user changeover]
#
# 做什么：
#   1) 建目录与服务账号            2) Python venv + 安装依赖
#   3) 生成 .env（自动生成 JWT_SECRET，其余按提示填写）
#   4) 建库 + 灌种子               5) 启动自检（preflight）
#   6) 安装 systemd 单元并启动     7) 打印访问地址与后续步骤
#
# 幂等：可重复执行（已存在的 venv/.env/服务会复用，不会覆盖 .env）。
# 说明：本脚本不安装 Nginx —— 默认「后端单端口托管前端」，最省事；
#      如需 Nginx 方案见 deploy/nginx-changeover.conf。
# =============================================================================
set -euo pipefail

INSTALL_DIR=/opt/changeover
RUN_USER=changeover
PORT=8000

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --user) RUN_USER="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "未知参数：$1"; exit 2 ;;
  esac
done

if [ "$(id -u)" != "0" ]; then
  echo "请用 root 或 sudo 执行（需要建用户、装 systemd 单元）。"; exit 1
fi

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "=============================================="
echo " 部署目录 : $INSTALL_DIR"
echo " 运行账号 : $RUN_USER"
echo " 源码目录 : $SRC_DIR"
echo "=============================================="

# ---- 0. 依赖命令检查 ----
command -v python3 >/dev/null || { echo "缺少 python3（建议 3.11+）"; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || {
  echo "Python 版本过低：$(python3 -V)（需 ≥3.10）"; exit 1; }

# ---- 1. 服务账号与目录 ----
if ! id "$RUN_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /sbin/nologin "$RUN_USER"
  echo "[1/7] 已创建服务账号 $RUN_USER"
else
  echo "[1/7] 服务账号已存在：$RUN_USER"
fi
mkdir -p "$INSTALL_DIR" /var/log/changeover
chown -R "$RUN_USER":"$RUN_USER" /var/log/changeover

# ---- 2. 代码落位 ----
if [ "$SRC_DIR" != "$INSTALL_DIR/backend" ]; then
  mkdir -p "$INSTALL_DIR/backend" "$INSTALL_DIR/frontend" "$INSTALL_DIR/docs"
  cp -rf "$SRC_DIR/app" "$SRC_DIR/scripts" "$SRC_DIR/tests" "$INSTALL_DIR/backend/" 2>/dev/null || true
  cp -f "$SRC_DIR/requirements.txt" "$SRC_DIR/requirements-dev.txt" "$SRC_DIR/.env.example" \
        "$INSTALL_DIR/backend/" 2>/dev/null || true
  [ -d "$SRC_DIR/deploy" ] && cp -rf "$SRC_DIR/deploy" "$INSTALL_DIR/backend/" || true
  [ -d "$SRC_DIR/../frontend/dist" ] && cp -rf "$SRC_DIR/../frontend/dist" "$INSTALL_DIR/frontend/" || true
  [ -d "$SRC_DIR/../docs" ] && cp -rf "$SRC_DIR/../docs/." "$INSTALL_DIR/docs/" || true
  echo "[2/7] 代码已复制到 $INSTALL_DIR"
else
  echo "[2/7] 已在部署目录内，跳过复制"
fi

# ---- 3. venv + 依赖 ----
cd "$INSTALL_DIR/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
./.venv/bin/python -m pip install --upgrade pip -q
./.venv/bin/python -m pip install -q -r requirements.txt
echo "[3/7] Python 依赖已安装（$(./.venv/bin/python -V)）"

# ---- 4. .env ----
if [ ! -f .env ]; then
  SECRET=$(./.venv/bin/python - <<'PY'
import secrets; print(secrets.token_urlsafe(48))
PY
)
  cat > .env <<EOF
# 由 deploy_linux.sh 生成于 $(date '+%F %T')
DB_PATH=$INSTALL_DIR/backend/data/app.db
JWT_SECRET=$SECRET
JWT_EXPIRE_HOURS=12

# ---- 前端单端口托管（后端同时提供 API 与页面）----
FRONTEND_DIST=$INSTALL_DIR/frontend/dist
SERVE_FRONTEND=auto
APP_HOST=0.0.0.0
APP_PORT=$PORT

# ---- SMB 照片共享（必填；生产必须用专用服务账号，禁用匿名）----
# 注意：systemd 不解析 export，反斜杠是转义符，Windows 风格路径请写双反斜杠
SMB_HOST=
SMB_SHARE=
SMB_ROOT=slenk_\\\\FA_ROOT
SMB_USER=
SMB_PASSWORD=
# SMB_DOMAIN=

# ---- 图片与草稿 ----
MAX_IMAGE_MB=10
MAX_IMAGE_EDGE=1920
DRAFT_TTL_DAYS=7

# ---- WB 参数查询 ----
# auto: 优先 wb_mail.mes_api，其次 HTTP 端点；也可显式 mes / http / mock / off
WB_SOURCE=auto
WB_MAIL_PATH=
TIOT_URL=
MID_API_URL=
ODF_URL=
MES_API_BASE=
MES_DOMAIN=
MES_REFERER=
# WB_BY_BATCH_URL=
# WB_BY_BOM_URL=

# ---- 种子管理员（仅首次建库生效，首次登录强制改密）----
SEED_ADMIN_EMP_ID=
SEED_ADMIN_NAME=
SEED_ADMIN_PASSWORD=
EOF
  chmod 600 .env
  chown "$RUN_USER":"$RUN_USER" .env
  echo "[4/7] 已生成 .env（JWT_SECRET 已随机生成）"
  echo "      ⚠ 请填写 SMB_* / SEED_ADMIN_* / WB_* 后重跑本脚本或重启服务："
  echo "        vi $INSTALL_DIR/backend/.env"
else
  echo "[4/7] .env 已存在，保留不覆盖"
fi

# 导出 .env 供建库/自检使用
set -a; . ./.env; set +a
mkdir -p "$(dirname "${DB_PATH:-$INSTALL_DIR/backend/data/app.db}")"
chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR/backend"

# ---- 5. 建库 + 种子 + 自检 ----
echo "[5/7] 建库并灌入字典/种子管理员（幂等）..."
mkdir -p "$(dirname "${DB_PATH:-$INSTALL_DIR/backend/data/app.db}")"
./.venv/bin/python -m app.seed || echo "（种子执行有告警，可忽略；首次启动也会自动灌入）"
echo "--- 启动自检 ---"
./.venv/bin/python -m app.preflight || echo "（自检有告警/致命项，请按上方提示处理）"

# ---- 6. systemd ----
if command -v systemctl >/dev/null 2>&1; then
  for unit in co.service co-maintenance.service co-maintenance.timer; do
    sed -e "s#/opt/changeover#$INSTALL_DIR#g" \
        -e "s#^User=changeover#User=$RUN_USER#" \
        -e "s#^Group=changeover#Group=$RUN_USER#" \
        "scripts/$unit" > "/etc/systemd/system/$unit"
  done
  systemctl daemon-reload
  systemctl enable --now co.service >/dev/null 2>&1 || systemctl start co.service
  systemctl enable --now co-maintenance.timer >/dev/null 2>&1 || true
  echo "[6/7] systemd 单元已安装并启动（含每日 03:30 维护定时器）"
else
  echo "[6/7] 未检测到 systemd：请手动启动，例如"
  echo "      cd $INSTALL_DIR/backend && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT"
fi

# ---- 7. 收尾 ----
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "[7/7] 完成。"
echo
echo "访问地址： http://${IP:-<服务器IP>}:$PORT/"
echo "接口文档： http://${IP:-<服务器IP>}:$PORT/docs"
echo "健康检查： curl http://127.0.0.1:$PORT/api/health"
echo
echo "常用运维："
echo "  systemctl status co            # 服务状态"
echo "  journalctl -u co -f            # 实时日志（或 tail -f /var/log/changeover/app.log）"
echo "  systemctl restart co           # 重启（改 .env 后需重启）"
echo "  systemctl start co-maintenance # 手动跑一次备份+草稿清理"
echo
echo "防火墙（如启用 firewalld）："
echo "  firewall-cmd --permanent --add-port=$PORT/tcp && firewall-cmd --reload"
echo
echo "⚠ 上线前务必：① 填 SMB_* 且改用专用服务账号；② 设 SEED_ADMIN_* 并首次登录改密；③ 确认 WB 数据源可用。"
