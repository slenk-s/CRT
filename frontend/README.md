# 转产测试追溯 CRT · 前端

Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router。
移动优先设计，桌面端与移动端共享同一套业务视图，并通过响应式布局统一体验。

## 目录结构

```text
frontend/
├─ index.html
├─ vite.config.ts          # 开发态 /api 反代到后端，免 CORS
├─ package.json            # dev / build / type-check / preview 脚本
├─ src/
│  ├─ main.ts              # Element Plus（中文语言包）+ 图标全局注册
│  ├─ App.vue              # 登录页独立全屏，其余走 AppShell
│  ├─ api/
│  │  ├─ http.ts           # axios 实例：token 注入、401/403/503 统一提示、图片 Blob 代理、CSV 下载
│  │  ├─ types.ts          # 与后端 Pydantic 模型一一对应
│  │  └─ index.ts          # 全部接口封装
│  ├─ stores/user.ts       # 登录态（token 持久化到 localStorage）
│  ├─ router/index.ts      # 登录守卫 + 管理员守卫
│  ├─ layouts/AppShell.vue # 顶部导航 + 移动端浮层导航 + 用户菜单 + 首次登录强制改密
│  ├─ components/AuthImage.vue  # 受保护图片（带 token 取 Blob 展示）
│  ├─ utils/image.ts       # 上传前压缩（长边 ≤1920，JPEG 0.85）
│  ├─ styles/index.css     # 响应式布局、登录视觉、顶部导航、工位状态图标
│  └─ views/
│     ├─ LoginView.vue                    # 登录页（旋转渐变描边 + 弥散背光 + 登录上拉转场）
│     ├─ ChangeoverListView.vue           # 转产记录：标题 / 导出 CSV / 新建转产 / 筛选卡 / 表格卡
│     ├─ ChangeoverEditView.vue           # 新建 + 逐工位录入 + 圆形 SVG checkbox + 统一提交
│     ├─ ChangeoverDetailView.vue         # 详情 + 更正（版本化）+ 版本历史弹窗
│     ├─ WbQueryView.vue                  # 按批次 / BOM 查询 WB 参数
│     ├─ StatsView.vue                    # 趋势（内置 SVG 折线，无额外图表依赖）
│     └─ admin/{DictManageView,UserManageView}.vue
```

## 开发（双端 8001）

```bash
# 终端 A：后端（读 .env，固定 8001 并 --reload）
cd ../backend
python scripts/start_dual.py       # uvicorn --reload --port 8001

# 终端 B：前端
cd frontend
npm install                        # 首次
npm run dev                        # http://localhost:5173
```

开发态由 Vite 代理 `/api` → `http://127.0.0.1:8001`（见 `.env.development` 的 `VITE_API_TARGET`）。
如需切回单端口 8000：把 `.env.development` 的 `VITE_API_TARGET` 改成 `http://127.0.0.1:8000`，再用 `uvicorn --port 8000` 启动后端即可。
## 构建与部署

```bash
npm run build        # 输出 dist/
npm run preview      # 本地预览 dist
npm run type-check   # Vue/TypeScript 类型检查
```

生产建议用 Nginx 托管 `dist/`，并把 `/api` 反代到后端：

```nginx
server {
    listen 80;
    root /opt/changeover/frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;   # history 路由回退
    }
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 20m;           # 照片上传
    }
}
```

后端也可单端口托管 `dist/`：见 `backend/README.md` 的 2.1 节。

## 关键约定

- **鉴权**：登录后 token 存 `localStorage[co_token]`，请求头 `Authorization: Bearer <token>`；401 统一跳登录。
- **首次登录/口令重置**：`must_change_password=1` 时前端强制改密弹窗，未改密无法使用。
- **照片**：`<img>` 无法携带 Authorization 头，统一经 `AuthImage` 用 Blob URL 展示；上传前前端压缩。
- **勾选结果**：`check_result` 为 JSON 字符串（`{"项目名": true}`），与后端契约一致。
- **已录/未录**：以有效输入为准。有任意勾选、备注或照片为 `已录`；点开但无勾选、无备注、无照片为 `未录`。
- **工位状态图标**：未录为红色圆环空白图标（`#f56c6c`）；已录为绿色圆环勾选图标（`#67c23a`）；所有工位行生效。
- **展开箭头**：工位行展开后箭头旋转 90° 向下，收起恢复向右，并带弹性缓动。
- **更正**：已提交记录修改走 `PUT`，后端生成新版本（`ver+1`），历史版本在版本历史弹窗中查看。
- **CSV 导出**：`GET /api/changeover/export.csv`，筛选条件与列表一致，UTF-8 BOM（Excel 直接打开不乱码）。
  按**工位条目一行**，列为现场台账设计：`日期/车间/线体/批次/工位/状态/版本/检查项/备注/照片数/文件名/上传人工号/上传人/提交时间`。
  检查项只列已勾选项（顿号分隔），多张照片合并到「文件名」一格（分号分隔），不含共享盘内部路径。
  行按批次号排序分组、批次之间留空行（CSV 上不了色，用留白代替色阶）。

## 响应式导航规则

- 桌面端：汉堡菜单永远最左侧；标题隐藏；横向导航显示；用户区永远最右侧。
- 移动端：汉堡菜单最左侧；用户区最右侧；标题和横向导航隐藏。
- 移动端点击汉堡后，从按钮附近展开浮层导航；关闭时原路收回；选择菜单项后自动关闭。
- 顶部导航保留登录页的深色渐变、动态模糊与呼吸弥散背光风格，形成登录后承接效果。

## 视觉与交互增强

- 登录卡片：旋转渐变描边、底部动态模糊弥散背光。
- 按钮：按压 `scale(0.96)` 压缩与内阴影；释放后轻微回弹。
- 版本历史：重构为紧凑弹窗，避免遮挡返回按钮或显示不全。
- 用户管理弹窗：限制为 `min(480px, 94vw)`，内部滚动，适配窄屏。
- 字典管理删除：线体/工位/检查项的删除按钮均为直接物理删除；是否停用由「停用/启用」控制。
