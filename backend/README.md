# 转产测试追溯 CRT

TCL 惠州 TV 工厂 PE 部 · 产线转产（Changeover）拍照记录与追溯系统。
轻量浏览器应用：转产建档 → 逐工位录入检查项 + 拍照 → 统一提交归档 → 按日期/线体/批次/工位追溯。

- **后端**：FastAPI + SQLAlchemy 2.0(SQLite) + bcrypt + PyJWT + smbprotocol
- **前端**：Vue3 + Vite + TypeScript + Element Plus + Pinia + Vue Router（`dist` 可预构建随包交付）
- **照片存储**：仅存 SMB 共享盘，数据库只存**共享内相对路径**

---

## 1. 目录结构

```text
├─ backend/
│  ├─ app/
│  │  ├─ main.py              # 入口：启动校验 → 建表 → 种子 → 挂载路由 / 可选托管前端
│  │  ├─ config.py            # 环境变量（不写死密钥/内网地址）
│  │  ├─ db.py                # SQLite 引擎 / 会话 / init_db
│  │  ├─ models.py            # 数据表模型
│  │  ├─ schemas.py           # Pydantic v2 请求/响应模型
│  │  ├─ security.py          # bcrypt 哈希 + JWT
│  │  ├─ deps.py              # 当前用户 / 管理员 / 存储依赖
│  │  ├─ seed.py              # 幂等种子（29 线体 / 11 工位 / 58 检查项 / 管理员）
│  │  ├─ routers/
│  │  │  ├─ auth.py           # 登录 / 当前用户 / 改密
│  │  │  ├─ dicts.py          # 字典读取
│  │  │  ├─ changeover.py     # 转产会话 / 条目 / 草稿照片 / 统一提交 / 版本纠错 / 图片代理 / CSV 导出
│  │  │  ├─ admin.py          # 管理端：线体/工位/检查项/用户（仅 admin）
│  │  │  ├─ reports.py        # 统计
│  │  │  └─ wb.py             # WB 参数查询（模块②，?batch= / ?bom=）
│  │  └─ services/
│  │     ├─ storage.py        # SMB 存储层（草稿/正式路径、读写、迁移、流式）
│  │     ├─ wb_source.py      # WB 数据源封装（mes_api / http / mock / off 可插拔）
│  │     └─ audit.py          # 审计日志 helper
│  ├─ tests/                  # pytest（含前端契约测试）
│  ├─ scripts/                # 部署与运维：deploy_linux.sh / deploy_windows.bat / start_backend.bat 等
│  ├─ deploy/                 # nginx-changeover.conf（方案 B：Nginx 托管前端）
│  ├─ requirements.txt        # 运行依赖
│  ├─ requirements-dev.txt    # 开发依赖（pytest/httpx）
│  └─ .env.example            # 环境变量样例
├─ frontend/
│  ├─ src/
│  │  ├─ layouts/AppShell.vue # 顶部导航 + 移动端浮层菜单 + 用户菜单
│  │  ├─ views/               # 登录 / 列表 / 录入 / 详情 / WB / 统计
│  │  ├─ views/admin/         # 字典管理 / 用户管理
│  │  └─ styles/index.css     # 响应式布局与交互样式
│  └─ dist/                   # 生产构建产物
```

---

## 2. 快速开始

### 2.1 本机测试态（Windows · 推荐一键）

```bat
cd backend
scripts\deploy_windows.bat      :: 建 venv → 装依赖 → 生成 .env → 建库灌种子 → 自检 → 放行防火墙
scripts\start_backend.bat       :: 启动（读 .env；默认优先 8001，占用则自动顺延）
```

- `start_backend.bat` 由 `scripts\load_env.py` 载入 `.env`，避免 CMD 批处理解析中文注释、URL 中 `=`、反斜杠等失败。
- 后端启动日志会打印实际端口；单端口模式下后端同时托管 `frontend/dist`。
- 若本机访问 `http://127.0.0.1:8000/` 被旧进程占用，可改用脚本实际打印的端口，或先结束占用 8000/8001 的进程。
- 手机/平板同局域网访问 `http://<本机IP>:<端口>/`；防火墙默认脚本放行的是 TCP 8000。

### 2.2 内网服务器态（Linux · 推荐一键）

```bash
cd backend
sudo bash scripts/deploy_linux.sh --dir /opt/changeover --user changeover
sudo vi /opt/changeover/backend/.env      # 填 SMB_* / SEED_ADMIN_* / WB_*
sudo systemctl restart co
```

安装 systemd 服务 `co.service` + 每日维护定时器 `co-maintenance.timer`（SQLite 备份 + 超期草稿清理）。
如需 Nginx 托管前端（方案 B）：`deploy/nginx-changeover.conf`，并把 `.env` 的 `SERVE_FRONTEND=off`。

### 2.3 开发态（前后端分离 · 双端 8001，推荐）

```bash
# 终端 A：后端（读 .env，固定 8001 并 --reload）
cd backend
pip install -r requirements-dev.txt        # 首次
python -m app.seed                          # 首次
python scripts/start_dual.py                # uvicorn --reload --port 8001

# 终端 B：前端
cd frontend
npm install                                 # 首次
npm run dev                                 # http://localhost:5173
```

开发态由 Vite 代理 `/api` → `http://127.0.0.1:8001`（见 `frontend/.env.development` 的 `VITE_API_TARGET`；若需切回单端口 8000，把它改为 `http://127.0.0.1:8000` 即可）。

### 2.4 启动自检

```bash
cd backend && python -m app.preflight          # 人类可读报告
python -m app.preflight --json                 # 机器可读（监控/CI）
python -m app.preflight --strict               # 有告警即失败
```

检查配置 / 数据库 / SMB 连通 / WB 数据源 / 前端 dist / MES 端点；致命项返回码 1。

---

## 3. 环境变量（`backend/.env.example`）

| 变量 | 说明 |
|---|---|
| `APP_HOST` / `APP_PORT` | 服务绑定地址与端口，缺省 `0.0.0.0` / `8000`；双端开发态用 `scripts/start_dual.py` 固定 `8001`，`start_backend.bat` 亦默认优先 `8001` |
| `DB_PATH` | SQLite 文件路径，缺省 `backend/data/app.db` |
| `JWT_SECRET` | 签发登录 token 的密钥（**必配**） |
| `JWT_EXPIRE_HOURS` | token 有效期，缺省 12 |
| `SMB_HOST` / `SMB_SHARE` | 共享服务器与共享名（**必配**，否则照片功能不可用） |
| `SMB_ROOT` | 共享内子路径，如 `slenk_\\FA_ROOT` |
| `SMB_USER` / `SMB_PASSWORD` / `SMB_DOMAIN` | 服务账号（生产建议专用账号，禁匿名） |
| `MAX_IMAGE_MB` / `MAX_IMAGE_EDGE` | 上传限制：最大 10 MB / 长边 1920 px |
| `DRAFT_TTL_DAYS` | 未提交草稿保留天数，缺省 7 |
| `FRONTEND_DIST` / `SERVE_FRONTEND` | 单端口托管前端目录；`auto`/`on`/`off` |
| `WB_SOURCE` | WB 数据源：`auto` / `mes` / `http` / `mock` / `off` |
| `WB_MAIL_PATH` / `WB_BY_BATCH_URL` / `WB_BY_BOM_URL` | WB 包路径或 HTTP 回退端点 |
| `TIOT_URL` / `MID_API_URL` / `ODF_URL` / `MES_API_BASE` / `MES_DOMAIN` / `MES_REFERER` | wb_mail / MES 端点（按现场填写） |
| `SEED_ADMIN_EMP_ID` / `SEED_ADMIN_NAME` / `SEED_ADMIN_PASSWORD` | 种子管理员（首次登录强制改密） |
| `WB_QUERY_CONCURRENCY` / `WB_QUERY_BUDGET_SECONDS` | WB 多批次查询并发度 / 整体预算秒数（默认 `6` / `60`，须 < 前端 axios 超时 120s） |
| `WB_FORCE_ENV_LOAD` | `1` 时强制重新拉取 T 盘端点文件（默认仅在缺失时拉取） |

---

## 4. 主要接口

所有业务接口需 `Authorization: Bearer <token>`。已提交会话的**会话级**写操作（加条目/改批次/删会话/PATCH 草稿）一律 409；**条目级**纠错改走 `PUT` 与照片替换（生成新版本）。

### 认证
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录 |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/change-password` | 修改口令 |

### 转产（模块①）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/changeover` | 分页列表（日期/线体/批次/状态/创建人筛选） |
| POST | `/api/changeover` | 新建转产会话（草稿） |
| GET | `/api/changeover/{id}` | 详情（含工位条目） |
| PATCH | `/api/changeover/{id}` | 修改草稿批次/备注 |
| DELETE | `/api/changeover/{id}` | 删除草稿会话（物理清草稿文件）；已提交会话返回 409 |
| GET | `/api/changeover/export.csv` | CSV 导出（UTF-8 BOM） |
| POST | `/api/changeover/{id}/items` | 添加工位条目 |
| PATCH | `/api/changeover/items/{item_id}` | 更新草稿勾选结果/备注 |
| PUT | `/api/changeover/items/{item_id}` | 已提交条目纠错（生成新版本） |
| DELETE | `/api/changeover/items/{item_id}` | 删条目（草稿清文件；已提交软删留历史） |
| POST | `/api/changeover/{id}/submit` | 统一提交归档 |
| POST | `/api/changeover/items/{item_id}/photo` | 上传/替换照片（草稿覆盖；已提交=新版本） |
| GET | `/api/changeover/items/{item_id}/photo?ver=` | 图片代理（草稿优先/指定版本，流式转发） |
| GET | `/api/changeover/items/{item_id}/versions` | 版本历史（倒序） |

### 管理端（仅 admin）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/admin/lines` | 线体（读含停用 / 新增） |
| PUT/DELETE | `/api/admin/lines/{id}` | 改（改名冲突 409）/ **物理删除** |
| POST | `/api/admin/lines/import` | 批量导入（粘贴「车间,线体」多行） |
| GET/POST | `/api/admin/stations` · PUT/DELETE `/api/admin/stations/{id}` | 工位管理（DELETE 为**物理删除**） |
| GET/POST | `/api/admin/check-items` · PUT/DELETE `/api/admin/check-items/{id}` | 检查项管理（DELETE 为**物理删除**） |
| GET/POST | `/api/admin/users` · PUT `/api/admin/users/{emp_id}` | 用户管理（禁自停用/自降级） |

### 统计（仅 admin）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stats/changeover?days=14` | 近 N 天提交/条目折线数据 + 线体 Top10 |

### WB 参数查询（模块②）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/wb/query?batch=` | 按批次查询（可逗号/换行分隔多个；有序字段原样透传） |
| GET | `/api/wb/query?bom=` | 按 BOM 查询 |
| GET | `/api/wb/status` | 数据源可用性（前端提示用） |

> `WB_SOURCE` 可选 `auto/mes/http/mock/off`：优先真实 `wb_mail.mes_api`，缺失则回退 HTTP 端点，都没有则 503「数据源未配置」。单批次失败逐条标注，不遮蔽其他。

> **并发查询（v1.2）**：多批次 / 多 BOM 查询使用 `ThreadPoolExecutor` 并发（默认 `WB_QUERY_CONCURRENCY=6`），整体预算 `WB_QUERY_BUDGET_SECONDS=60`（须 < 前端 axios 超时 120s）；超预算条目标记 `ok=false` + 「查询超时」，避免拖到前端超时。关键字去重 + 逐条耗时日志。可用 `WB_FORCE_ENV_LOAD=1` 强制重新拉取 T 盘端点。

---

## 5. 存储路径约定

```text
草稿区  {SMB_ROOT}/_draft/{changeover_id}/{item_id}.{ext}
正式区  {SMB_ROOT}/{YYYY-MM-DD}/{line}/{batch}/{station}/{HHMMSS}_{工号}_v{ver}.{ext}
```

- 拍照即上传草稿区；**统一提交**时 `move` 到正式区并生成 `co_item_version` 的 v1 记录。
- 提交后**纠错**：更正勾选/备注 → 版本 `ver+1`（复用原照片）；替换照片 → 写新版本文件 `_v{ver}`（旧版文件保留）。
- 文件迁移失败只影响该条目并回报，不阻塞整单；草稿文件缺失的条目提交失败、其余照常转正。

---

## 6. 测试

```bash
cd backend
pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest tests -q
```

- `test_smoke.py`：健康检查 / 认证 / 字典。
- `test_changeover.py`：转产草稿链路（会话/条目/草稿照片/锁定）。
- `test_submit.py`：统一提交 / 版本化纠错 / 正式图代理。
- `test_admin.py`：字典/用户管理、权限边界、线体/工位/检查项删除行为。
- `test_reports.py`：CSV 导出 BOM、统计结构。
- `test_wb.py`：WB 查询 mock 源、单条失败、参数校验、503 降级。
- `test_api_contract.py`：前端契约（复现前端请求形状：路径/参数/multipart/CSV BOM/权限边界）。
- 全部用例用内存 `FakeStorage` 覆盖 `get_storage` 依赖，不依赖内网。
- 运维脚本自检：`python scripts/cleanup_drafts.py --dry-run`（草稿清理预演）。
- SMB 层真实链路自检：`python -m app.services.storage`（需配置 `SMB_*`）。

前端构建与类型检查：

```bash
cd frontend
npm run build
npm run type-check
```

---

## 7. 安全与运维注意

- 生产环境**必须**关闭匿名访问，改用专用服务账号；`JWT_SECRET` 使用强随机值并仅存于 `.env`。
- `.env`、`*.db`、`__pycache__` 已加入 `.gitignore`，请勿入库。
- 字典停用（`active=0`）用于业务停用与新建时过滤；字典「删除」按钮为**物理删除**，已有转产历史记录保留，不再依赖软删项保留字典行。
- 记录删除：草稿会话删除会物理清理草稿文件；已提交条目删除采用软删（`is_deleted=1`）并保留版本历史。
- 所有关键写操作落 `audit_log`。

---

## 8. 进度与路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 骨架 / 依赖 / 配置 | ✅ |
| 1 | DB / 模型 / 认证 / 种子 | ✅ |
| 2 | 入口 / 依赖 / 登录 / 字典接口 | ✅ |
| 3.1 | SMB 存储层 | ✅ |
| 3.2–3.3 | 转产会话 / 条目 / 草稿照片 API | ✅ |
| 3.4 | 字典 / 用户管理端（仅 admin） | ✅ |
| 4 | 统一提交 / 版本化纠错 / 正式图代理 | ✅ |
| 5 | 导出 CSV / 统计 | ✅ |
| 6 | WB 参数查询（接入 wb_mail） | ✅ |
| 7 | 前端（Vue3 + Element Plus） | ✅ |
| 8 | 测试（pytest + 前端契约） | ✅ |
| 9 | 部署（本机 / 内网 systemd） | ✅ |

---

## 9. 文档索引

- `frontend/README.md`：前端开发、构建与部署约定。
