# 产线转产管理轻应用

TCL 惠州 TV 工厂 PE 部 · 产线转产（Changeover）拍照记录与追溯系统。

轻量浏览器应用：转产建档 → 逐工位录入检查项 + 拍照 → 统一提交归档 → 按日期/线体/批次/工位追溯。

当前版本：**v1.2**（对齐 `PCC v1.2 修复合并包`）

## 文档入口

- `backend/README.md`：后端开发、接口、配置、测试、部署入口
- `frontend/README.md`：前端开发、构建、响应式规则、视觉交互
- `docs/阶段9-部署说明.md`：Windows / Linux / systemd / Nginx / 故障排查
- `docs/阶段10-UI与删除策略增量说明.md`：最新 UI、状态判定、删除策略增量

## 常用启动

### 本机双端模式（推荐，当前使用）

后端 `8001` + 前端 `5173`，前端通过 Vite 代理转发 `/api`，避免 CORS。

```powershell
# 后端（自动加载 backend/.env，固定 8001，--reload 热更）
cd backend
& '.venv\Scripts\Python311.exe' scripts\start_dual.py

# 前端（另开一个终端）
cd frontend
npm run dev          # http://localhost:5173  局域网 http://192.168.3.13:5173
```

端口对齐：`frontend/.env.development` 的 `VITE_API_TARGET=http://127.0.0.1:8001`。
如需切回 `8000`，改这里 + `scripts/start_dual.py` 的 `APP_PORT` 即可。

### 本机单端口模式（生产预览）

后端直接托管 `frontend/dist`（`SERVE_FRONTEND=auto`），只开一个端口。

```bash
cd backend
pip install -r requirements-dev.txt
python -m app.seed
python -m uvicorn app.main:app --reload --port 8000
# 浏览器访问 http://localhost:8000/
```

### 生产/内网部署

```bash
cd backend
sudo bash scripts/deploy_linux.sh --dir /opt/changeover --user changeover --port 8000
sudo vi /opt/changeover/backend/.env
sudo systemctl restart co
```

## v1.2 变更记录

对齐《PCC v1.2 修复合并包》，核心变化：

### 后端
- **`app/routers/wb.py`**：多批次查询改为并发（`ThreadPoolExecutor`，并发度 `WB_QUERY_CONCURRENCY=6`，整体预算 `WB_QUERY_BUDGET_SECONDS=60`）。关键字去重 + 逐条耗时日志 + 超时条目标记 ok=false，避免拖到前端超时。
- **`app/services/wb_source.py`**：端点注入只做一次（`threading.Lock` + `_ENDPOINTS_LOADED`），端点已由 `.env/systemd` 预置时跳过每次请求都起 `tchat-cli` 子进程拉 T 盘端点文件的开销；仅缺失或 `WB_FORCE_ENV_LOAD=1` 时拉取。

### 前端
- **新增 `src/stores/wb.ts`**：WB 查询状态提升到 Pinia，`sessionStorage` 持久化、代次（generation）防过期响应回填、`stop()` 真正终止在途请求、切页不丢数据。
- **`src/views/WbQueryView.vue`**：改用 `useWbStore`；进行中按钮显示「终止」，空闲显示「清空」；示例值改为真实批次/BOM（GHH500277A / GLU500297A / Z2U10401010120 / Z2U10401008960）。
- **`src/api/http.ts`**：`ECONNABORTED` / `ETIMEDOUT` 显式提示「请求超时」/「网络异常」，不再静默失败。
- **`src/api/index.ts`**：`wbQuery` 支持 `AbortSignal`；WB 查询专属超时 120s（> 后端 60s 预算），其他接口保持默认。
- **`src/views/LoginView.vue`**：登录错误弹层出现后 1s 开始淡出、约 2s 完成渐隐，可点击立即关闭，组件卸载清理定时器，与登录页主题一致。
- **`src/layouts/AppShell.vue`**：完整的移动端导航（顶部弹层 + 圆角卡片 + `backdrop-filter` 模糊 + 逐项 stagger 动画 + 下拉菜单圆角）。

### 环境变量
`backend/.env` 新增：
- `WB_QUERY_CONCURRENCY=6`
- `WB_QUERY_BUDGET_SECONDS=60`

## 关键说明

- 业务文案统一为「转产」；历史接口路径仍保留 `/changeover`。
- 线体/工位/检查项删除按钮为**物理删除**；停用/启用由 `active=0/1` 控制。
- 已提交转产条目删除为**软删**并保留版本历史。
- 后端可单端口托管 `frontend/dist`，也可由 Nginx 托管前端并反代 `/api`。
- `.env` 含密钥与内网地址，已加入 `.gitignore`，请勿外发。