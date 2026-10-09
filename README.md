# 产线转产管理轻应用

TCL 惠州 TV 工厂 PE 部 · 产线转产（Changeover）拍照记录与追溯系统。

轻量浏览器应用：转产建档 → 逐工位录入检查项 + 拍照 → 统一提交归档 → 按日期/线体/批次/工位追溯。

## 文档入口

- `backend/README.md`：后端开发、接口、配置、测试、部署入口
- `frontend/README.md`：前端开发、构建、响应式规则、视觉交互
- `docs/阶段9-部署说明.md`：Windows / Linux / systemd / Nginx / 故障排查
- `docs/阶段10-UI与删除策略增量说明.md`：最新 UI、状态判定、删除策略增量

## 常用启动

### 本机测试态（推荐）

```bat
cd backend
scripts\deploy_windows.bat      :: 建 venv → 装依赖 → 生成 .env → 建库灌种子 → 自检 → 放行防火墙
scripts\start_backend.bat       :: 启动（读 .env；默认优先 8001，占用则自动顺延）
```

### 前后端分离开发

```bash
# 后端
cd backend
pip install -r requirements-dev.txt
python -m app.seed
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev          # http://localhost:5173
```

### 生产/内网部署

```bash
cd backend
sudo bash scripts/deploy_linux.sh --dir /opt/changeover --user changeover --port 8000
sudo vi /opt/changeover/backend/.env
sudo systemctl restart co
```

## 关键说明

- 业务文案统一为“转产”；历史接口路径仍保留 `/changeover`。
- Windows `scripts\start_backend.bat` 默认优先 `8001`，便于前后端分离联调。
- 线体/工位/检查项删除按钮为**物理删除**；停用/启用由 `active=0/1` 控制。
- 已提交转产条目删除仍为软删并保留版本历史。
- 后端可单端口托管 `frontend/dist`，也可由 Nginx 托管前端并反代 `/api`。
