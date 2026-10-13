# 转产测试追溯 CRT v1.2

TCL 惠州 TV 工厂 PE 部 · 产线转产（Changeover）拍照记录与追溯系统。

轻量浏览器应用：**转产建档 → 逐工位录入检查项 + 拍照 → 统一提交归档 → 按日期 / 线体 / 批次 / 工位追溯**。

- 版本：**v1.2**（已对齐《CRT v1.2 修复合并包》）
- 架构：FastAPI + SQLAlchemy + SQLite（后端） · Vue 3 + Vite + Pinia + Tailwind（前端）
- 仓库：https://github.com/slenk-s/CRT

---

## 目录

- [目录](#目录)
- [功能概览](#功能概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
  - [一键启动（推荐）](#一键启动推荐)
  - [双端模式（本地开发）](#双端模式本地开发)
  - [单端口模式（生产预览）](#单端口模式生产预览)
- [生产部署](#生产部署)
- [配置说明](#配置说明)
- [API 一览](#api-一览)
- [数据模型](#数据模型)
- [前端页面](#前端页面)
- [v1.2 变更记录](#v12-变更记录)
- [常见问题](#常见问题)
- [关键说明](#关键说明)

---

## 功能概览

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| 转产列表 | `/changeover` | 按「日期 + 线体 + 批次」管理转产会话，草稿可续录，提交后版本化留存 |
| 转产详情 | `/changeover/:id` | 逐工位查看检查项与照片，含版本历史 |
| 转产编辑 | `/changeover/:id/edit` | 逐工位录入检查项 + 拍照上传 |
| 条目统计 | `/stats` | 转产 / 检查项 / 批次维度统计看板 |
| 条目查询 | `/wb` | 按批次号或 BOM 查询白平衡（WB）参数，支持多关键字并发 |
| 系统管理 | `/admin` | 线体、工位、检查项、用户、审计日志、草稿清理 |
| 登录 | `/login` | JWT 认证，管理员首次种子默认密码 |

---

## 技术栈

### 后端
- Python 3.11 · FastAPI · SQLAlchemy 2.x · SQLite · Pydantic v2
- JWT 认证（`PyJWT`）、并发白平衡查询（`ThreadPoolExecutor`）
- 依赖注入（DI）、审计日志、种子初始化

### 前端
- Vue 3 · Vite 6 · TypeScript · Pinia · Vue Router 4 · Tailwind CSS
- Element Plus · Axios · Vitest（单元测试）

---

## 项目结构

```
CRT/
├── start.bat                  # 一键启动脚本（双端 / 单端口可选）
├── README.md                  # 本文件
├── .gitignore
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + 前端静态托管
│   │   ├── config.py          # 配置读取（含 SERVE_FRONTEND / APP_PORT）
│   │   ├── database.py        # SQLAlchemy 引擎 + session
│   │   ├── models.py          # ORM 模型
│   │   ├── schemas.py         # Pydantic schemas
│   │   ├── seed.py            # 幂等种子（线体 / 工位 / 检查项 / 管理员）
│   │   ├── routers/           # 接口路由
│   │   │   ├── auth.py        # 登录 / 当前用户
│   │   │   ├── changeover.py  # 转产会话 CRUD + 提交 + 版本
│   │   │   ├── wb.py          # 白平衡查询（并发 + 预算）
│   │   │   ├── dicts.py       # 线体 / 工位 / 检查项
│   │   │   ├── reports.py     # 条目统计
│   │   │   └── admin.py       # 后台管理（用户 / 审计 / 草稿）
│   │   └── services/
│   │       ├── audit.py       # 审计日志
│   │       ├── storage.py     # 上传文件存储（本地 / SMB）
│   │       └── wb_source.py   # WB 端点源（T 盘 / .env）
│   ├── scripts/               # 部署与运维脚本
│   │   ├── start_dual.py      # 双端口开发模式（8001）
│   │   ├── start_backend.bat  # Windows 后端单端口
│   │   ├── load_env.py        # 加载 .env 并启动 uvicorn
│   │   ├── deploy_windows.bat
│   │   ├── deploy_linux.sh
│   │   └── ...
│   ├── data/                  # SQLite 数据库 + 上传文件
│   ├── tests/
│   ├── .env                   # 本地环境变量（含密钥，不入库）
│   ├── .env.example
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── README.md
└── frontend/
    ├── src/
    │   ├── api/               # axios 封装 + 业务接口
    │   ├── stores/            # Pinia（user / wb）
    │   ├── views/             # 页面
    │   │   ├── LoginView.vue
    │   │   ├── ChangeoverListView.vue
    │   │   ├── ChangeoverDetailView.vue
    │   │   ├── ChangeoverEditView.vue
    │   │   ├── StatsView.vue
    │   │   ├── WbQueryView.vue
    │   │   └── admin/
    │   ├── layouts/AppShell.vue
    │   └── ...
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    ├── .env.development
    └── README.md
```

---

## 快速开始

### 前置要求

- Windows 10 / 11 或 Linux
- Python 3.11+
- Node.js 18+ 与 npm
- 可选：内网 SMB 共享盘（存储拍照附件）

### 首次初始化

```powershell
# Windows
cd backend
scripts\deploy_windows.bat    # 建 venv、装依赖、复制 .env.example → .env
```

```bash
# Linux / macOS
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

cd ../frontend
npm install
```

> `.env.example` 已含默认管理员账号 `admin / admin123`，首次启动会自动种子化。

### 一键启动（推荐）

双击根目录 `start.bat`，或在终端执行：

```powershell
cd C:\path\to\CRT
cmd /c start.bat
```

菜单：

```
============================================
  CRT v1.2 Launcher
============================================
  [1] Dual-port mode
      Backend : http://127.0.0.1:8001
      Frontend: http://127.0.0.1:5173
  [2] Single-port mode
      Backend + Frontend: http://127.0.0.1:8000
  [q] Quit
============================================
Select option:
```

脚本特性：
- **端口占用检查**：启动前 `netstat` 检查端口，被占会列出 PID 并交互询问是否 kill
- **双端模式**：启动两个新窗口（后端 `start_dual.py` + 前端 `npm run dev`），主窗口 6 秒后关闭；运行期自动清理生成的辅助脚本
- **单端口模式**：前台跑 `load_env.py`（uvicorn），`SERVE_FRONTEND=auto` 自动托管 `frontend/dist`；缺失会先 `npm run build`
- **Ctrl+C** 停止单端口后回到菜单

### 双端模式（本地开发）

后端 `8001` + 前端 `5173`，前端通过 Vite 代理转发 `/api`，避免 CORS。

```powershell
# 后端（自动加载 .env，固定 8001，--reload 热更）
cd backend
& '.venv\Scripts\Python311.exe' scripts\start_dual.py

# 前端（另开一个终端）
cd frontend
npm run dev          # http://localhost:5173
```

- 端口对齐：`frontend/.env.development` 中 `VITE_API_TARGET=http://127.0.0.1:8001`
- 如要切回 `8000`，改这里 + `scripts/start_dual.py` 的 `APP_PORT`

### 单端口模式（生产预览）

后端直接托管 `frontend/dist`（`SERVE_FRONTEND=auto`），只开一个端口。

```bash
cd backend
npm run build       # 前端已 build 到 dist/（如首次）
cd ..
cd frontend && npm run build && cd ..   # 首次构建

cd backend
python -m app.seed                                  # 幂等初始化种子数据
python -m uvicorn app.main:app --reload --port 8000
# 浏览器访问 http://localhost:8000/
```

`SERVE_FRONTEND` 三种取值：
- `auto`（默认）：`frontend/dist/index.html` 存在则托管，否则仅 API
- `on`：强制托管，缺失则报错
- `off`：永不托管，仅 API

---

## 生产部署

### Linux（systemd + Nginx 推荐）

```bash
cd backend
sudo bash scripts/deploy_linux.sh \
    --dir /opt/changeover \
    --user changeover \
    --port 8000

sudo vi /opt/changeover/backend/.env      # 修改密钥、SMB 路径等
sudo systemctl restart co
sudo systemctl enable co
```

Nginx 反代示例：

```nginx
server {
    listen 80;
    server_name crt.local;
    client_max_body_size 50M;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 180s;
    }

    location / {
        root /opt/changeover/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

### Windows Server

```powershell
cd backend
scripts\deploy_windows.bat
scripts\install_autostart_windows.bat   # 注册开机自启
```

---

## 配置说明

关键环境变量（`backend/.env`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `APP_HOST` | `0.0.0.0` | 监听地址 |
| `APP_PORT` | `8000` | 监听端口（双端开发态由 `start_dual.py` 覆盖为 `8001`） |
| `SERVE_FRONTEND` | `auto` | `auto` / `on` / `off`，是否托管前端静态文件 |
| `JWT_SECRET` | — | JWT 签名密钥（**必须改**） |
| `SEED_ADMIN_PASSWORD` | `admin123` | 首次种子管理员密码 |
| `STORAGE_MODE` | `local` | `local` / `smb` |
| `STORAGE_LOCAL_ROOT` | `./data/uploads` | 本地上传根目录 |
| `SMB_ROOT` / `SMB_USER` / `SMB_PASSWORD` | — | SMB 共享盘配置 |
| `WB_QUERY_CONCURRENCY` | `6` | WB 多关键字并发度 |
| `WB_QUERY_BUDGET_SECONDS` | `60` | WB 单请求整体预算（**必须 < 前端 axios 超时 120s**） |
| `WB_ENDPOINTS_FILE` | — | WB 端点文件（T 盘） |
| `WB_FORCE_ENV_LOAD` | `0` | 强制每次请求重新拉取端点 |

数据库：SQLite 默认在 `backend/data/changeover.db`，可通过 `DATABASE_URL` 切换。

---

## API 一览

前缀统一 `/api`。除登录外均需 `Authorization: Bearer <token>`。

### 认证
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录，返回 JWT |
| GET | `/api/auth/me` | 当前用户 |

### 转产
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/changeover` | 列表（日期区间 / 线体 / 批次 / 状态 / 仅看我的） |
| POST | `/api/changeover` | 新建草稿 |
| GET | `/api/changeover/{id}` | 详情 |
| PATCH | `/api/changeover/{id}` | 更新草稿批次 / 备注 |
| DELETE | `/api/changeover/{id}` | 删除草稿（连草稿照片一起清）；已提交返回 409 |
| GET | `/api/changeover/export.csv` | CSV 导出（UTF-8 BOM） |
| POST | `/api/changeover/{id}/items` | 添加工位条目 |
| PATCH | `/api/changeover/items/{item_id}` | 改草稿勾选结果 / 备注 |
| PUT | `/api/changeover/items/{item_id}` | 已提交条目纠错（生成新版本） |
| DELETE | `/api/changeover/items/{item_id}` | 删条目（草稿清文件；已提交软删留历史） |
| POST | `/api/changeover/{id}/submit` | 统一提交归档（生成 v1） |
| POST | `/api/changeover/items/{item_id}/photo` | **追加**照片 |
| PUT | `/api/changeover/items/{item_id}/photos/{seq}` | **替换**指定序号的照片 |
| DELETE | `/api/changeover/items/{item_id}/photos/{seq}` | 删单张照片（仅草稿态） |
| GET | `/api/changeover/items/{item_id}/photos/{seq}` | 按序号取图 |
| GET | `/api/changeover/items/{item_id}/photo?ver=` | 图片代理（缺省=草稿/首张） |
| GET | `/api/changeover/items/{item_id}/versions` | 版本历史（倒序） |

### 白平衡查询
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/wb/query` | 多关键字并发查询（body: `keywords: string[]`） |

### 字典
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/dicts/lines` | 线体 |
| GET | `/api/dicts/stations` | 工位 |
| GET | `/api/dicts/check-items` | 检查项 |

### 统计
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/reports/stats` | 转产 / 检查项 / 批次维度统计 |

### 后台
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST / PUT / DELETE | `/api/admin/{lines,stations,check-items,users}` | 字典与用户 CRUD |
| GET | `/api/admin/audits` | 审计日志 |
| POST | `/api/admin/drafts/cleanup` | 草稿清理 |

---

## 数据模型

- **Line**：线体（`name`, `active`）
- **Station**：工位（`line_id`, `name`, `sort`, `active`）
- **CheckItem**：检查项（`name`, `category`, `active`）
- **User**：管理员（`username`, `password_hash`, `role`）
- **Changeover**：转产会话（`date`, `line_id`, `batch_no`, `status`, `version`）
- **ChangeoverItem**：转产条目（`changeover_id`, `station_id`, `check_item_id`, `result`, `photo_path`, `note`）
- **ChangeoverVersion**：转产版本快照（软删保留历史）
- **AuditLog**：审计日志

---

## 前端页面

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/login` | LoginView | JWT 登录，错误提示与主题一致（1s 淡出 + 1s 渐隐） |
| `/changeover` | ChangeoverListView | 转产列表（草稿续录、提交、版本查看） |
| `/changeover/:id` | ChangeoverDetailView | 详情 + 版本历史 |
| `/changeover/:id/edit` | ChangeoverEditView | 逐工位录入 + 拍照 |
| `/stats` | StatsView | 条目统计看板 |
| `/wb` | WbQueryView | WB 参数查询（多关键字并发，可终止） |
| `/admin/*` | AdminViews | 系统管理 |

移动端：`AppShell.vue` 顶部弹层导航 + 圆角卡片 + `backdrop-filter` 模糊 + 逐项 stagger 动画。

---

## v1.2 变更记录

对齐《CRT v1.2 修复合并包》：

### 后端
- **`app/routers/wb.py`**：多批次查询改为并发（`ThreadPoolExecutor`，并发度 `WB_QUERY_CONCURRENCY=6`，整体预算 `WB_QUERY_BUDGET_SECONDS=60`）。关键字去重 + 逐条耗时日志 + 超时条目标记 `ok=false`，避免拖到前端超时。
- **`app/services/wb_source.py`**：端点注入只做一次（`threading.Lock` + `_ENDPOINTS_LOADED`），端点已由 `.env` / systemd 预置时跳过每次请求都起 `tchat-cli` 子进程拉 T 盘端点文件的开销；仅缺失或 `WB_FORCE_ENV_LOAD=1` 时拉取。

### 前端
- **新增 `src/stores/wb.ts`**：WB 查询状态提升到 Pinia，`sessionStorage` 持久化、代次（generation）防过期响应回填、`stop()` 真正终止在途请求、切页不丢数据。
- **`src/views/WbQueryView.vue`**：改用 `useWbStore`；进行中按钮显示「终止」，空闲显示「清空」；示例值改为真实批次 / BOM（`GHH500277A` / `GLU500297A` / `Z2U10401010120` / `Z2U10401008960`）。
- **`src/api/http.ts`**：`ECONNABORTED` / `ETIMEDOUT` 显式提示「请求超时」/「网络异常」，不再静默失败。
- **`src/api/index.ts`**：`wbQuery` 支持 `AbortSignal`；WB 查询专属超时 120s（> 后端 60s 预算），其他接口保持默认。
- **`src/views/LoginView.vue`**：登录错误弹层 1s 后开始淡出、约 2s 完成渐隐，可点击立即关闭，组件卸载清理定时器，与登录页主题一致。
- **`src/layouts/AppShell.vue`**：完整的移动端导航（顶部弹层 + 圆角卡片 + `backdrop-filter` 模糊 + 逐项 stagger 动画 + 下拉菜单圆角）。

### 新增
- **`start.bat`**：一键启动脚本（双端 / 单端口可选菜单）

---

## 常见问题

**Q: 端口被占用怎么办？**
`start.bat` 会交互询问是否 kill；或手动 `taskkill /F /PID <pid>`（Windows）、`lsof -ti:8000 | xargs kill`（Linux）。

**Q: 前端 5173 无法访问后端？**
确认 `frontend/.env.development` 里 `VITE_API_TARGET=http://127.0.0.1:8001`，且 Vite 正在跑。

**Q: 单端口模式访问 `/` 返回 404？**
确保 `frontend/dist/index.html` 存在（先 `npm run build`），且 `SERVE_FRONTEND` 不是 `off`。

**Q: 白平衡查询超时？**
- 后端：`WB_QUERY_BUDGET_SECONDS` 默认 60s
- 前端：WB 接口 axios 超时 120s（**必须 > 后端预算**）
- 前端 `/wb` 页面进行中可按「终止」按钮

**Q: 修改 `.env` 后如何生效？**
- 双端：`uvicorn --reload` 会自动重启
- 单端口 / 生产：重启服务（`Ctrl+C` 或 `systemctl restart co`）

**Q: 首次种子默认密码？**
`admin / admin123`，首次登录后请立即修改。

---

## 关键说明

- 业务文案统一为「**转产**」；历史接口路径仍保留 `/changeover`。
- 线体 / 工位 / 检查项删除按钮为**物理删除**；停用 / 启用由 `active=0/1` 控制。
- 已提交转产条目删除为**软删**并保留版本历史。
- 后端可单端口托管 `frontend/dist`，也可由 Nginx 托管前端并反代 `/api`。
- `.env` 含密钥与内网地址，已加入 `.gitignore`，**请勿外发**。
- Windows 一键启动：根目录 `start.bat`，选择 `1` 双端 / `2` 单端口 / `q` 退出。

---

## 许可证

内部项目，仅供 TCL 惠州 TV 工厂 PE 部使用。
