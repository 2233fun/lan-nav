# 邻页 · 技术说明

本文面向维护者和希望了解实现细节的读者，覆盖架构、数据模型、API、链接检测、Markdown 渲染、
前端交互、备份恢复和测试。

部署和使用步骤请见 [部署与使用说明](USER-GUIDE.md)。

## 1. 设计目标

- 面向可信局域网，**不做登录和权限系统**；
- 分组支持任意深度，链接和文档按分组归属；
- 前端无构建步骤、无外部 CDN，静态文件由后端直接提供；
- 单机部署，SQLite 存储，尽量降低安装和维护成本；
- 页面首屏不等待链接检测，检测结果异步填充；
- 数据库支持多人同时读写，但不做实时推送和冲突合并；
- 所有写操作使用事务，导入前自动备份。

### 非目标

- 公网多租户、账号体系、细粒度权限；
- 实时协同编辑、操作审计、版本历史；
- 富文本编辑器；
- 分布式部署和多 worker 共享缓存；
- 对目标网站做内容级健康检查。

## 2. 总体架构

```text
浏览器
  │  HTML / CSS / JS（无构建、无 CDN）
  ▼
FastAPI 应用
  ├── /api/*        JSON API
  ├── /             单页入口
  ├── /static/*     静态资源
  ├── SQLite        分组 / 链接 / 文档
  └── HTTPX         服务端发起链接连通性检测
```

- 应用通过 `create_app()` 工厂创建，启动时初始化数据库；
- 每个请求通过依赖注入获取独立的 SQLite 连接，请求结束后关闭；
- 前端状态保存在内存中，不做 URL 路由；
- 链接检测由服务端发起，结果只缓存在进程内存，不写入数据库。

## 3. 技术栈

| 组件 | 版本/说明 |
| --- | --- |
| Python | ≥ 3.10 |
| FastAPI | 0.115.14 |
| Uvicorn | 0.54.0 |
| HTTPX | 0.28.1 |
| markdown-it-py | ≥ 3.0.0 |
| pytest | 9.2.0（开发依赖） |
| SQLite | Python 标准库 `sqlite3` |
| 前端 | 原生 HTML / CSS / JavaScript |
| 环境管理 | uv，锁文件 `uv.lock` |

已在 Ubuntu 24.04 / Python 3.12.3 环境验证。`pyproject.toml` 要求 Python ≥ 3.10；
Python 3.10 下使用 `tomli` 读取 TOML，3.11+ 使用标准库 `tomllib`。

## 4. 目录结构

```text
lan-nav/
├── app/
│   ├── api.py            # FastAPI 应用工厂、路由、请求模型、错误处理
│   ├── db.py             # 建表、连接、树查询、搜索、导入导出
│   ├── checker.py        # 限并发 HTTP 连通性检测与 TTL 缓存
│   ├── backup.py         # SQLite 在线备份、校验与恢复
│   ├── config.py         # 配置读取与数据路径
│   ├── main.py           # uvicorn app.main:app 入口
│   ├── __main__.py       # python -m app 生产入口
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── tests/                # pytest 接口、配置、文档与检测测试
├── docs/
│   ├── USER-GUIDE.md
│   ├── TECHNICAL.md
│   ├── screenshot.png
│   └── screenshot-mobile.png
├── pyproject.toml
├── uv.lock
├── run.sh                # 生产启动（环境校验 + 非热重载）
├── run-dev.sh            # 开发启动（热重载）
├── LICENSE
├── NOTICE
└── README.md
```

### 模块职责

- `app/api.py`：应用工厂、Pydantic 请求模型、全部 API、静态文件挂载、安全响应头、错误处理器。
- `app/db.py`：SQLite schema、连接参数、树结构构建、搜索、导入导出。
- `app/checker.py`：异步 HTTP 检测器、错误归类、TLS 降级重试、内存缓存。
- `app/backup.py`：SQLite 在线备份、备份文件校验、恢复前自动备份。
- `app/config.py`：环境变量、TOML 配置、XDG 默认路径和版本读取。
- `app/__main__.py`：读取配置并启动 Uvicorn，不启用热重载。
- `app/main.py`：供 `uvicorn app.main:app` 使用的 ASGI 入口。
- `app/static/app.js`：单页状态、树渲染、卡片、弹窗、文档栏、拖动排序、检测交互。

## 5. 数据模型

### 5.1 表结构

```sql
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
    url         TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    icon        TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(name)) > 0),
    content     TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(group_id, name)
);

CREATE INDEX IF NOT EXISTS idx_groups_parent
    ON groups(parent_id, sort_order, id);

CREATE INDEX IF NOT EXISTS idx_links_group
    ON links(group_id, sort_order, id);

CREATE INDEX IF NOT EXISTS idx_documents_group
    ON documents(group_id, sort_order, id);
```

要点：

- `groups.parent_id` 自引用，删除父分组时通过外键级联删除整棵子树；
- `links.group_id`、`documents.group_id` 均为 `ON DELETE CASCADE`；
- 文档名使用 `COLLATE NOCASE`，同一分组内不区分大小写去重；
- 排序统一使用 `sort_order ASC, id ASC`；
- 时间戳为 UTC ISO 8601，秒级精度，以 `Z` 结尾；
- 没有用户表，也没有操作者字段。

### 5.2 SQLite 参数

初始化时设置：

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

每次连接设置：

```sql
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

- WAL 允许读操作和写操作更好地并发；
- 写操作由 SQLite 串行化，适合小规模局域网多人使用；
- 连接超时为 10 秒，遇到锁时最多等待 5 秒；
- 每个请求使用独立连接，不跨请求共享。

### 5.3 树结构与计数

`build_tree()` 一次查询分组、链接和文档，在内存中组装树。每个分组包含：

```json
{
  "id": 3,
  "parent_id": 2,
  "name": "运维监控",
  "sort_order": 10,
  "links": [],
  "children": [],
  "direct_link_count": 2,
  "total_link_count": 2,
  "direct_document_count": 1,
  "total_document_count": 1,
  "created_at": "2026-10-29T04:50:00Z",
  "updated_at": "2026-10-29T04:50:00Z"
}
```

- `direct_link_count`：直属链接数；
- `total_link_count`：含所有子孙分组的链接数；
- `direct_document_count`：直属文档数；
- `total_document_count`：含所有子孙分组的文档数。

`GET /api/tree` 顶层还包含 `total_groups`、`total_links`、`total_documents`、`version`
和 `generated_at`。

### 5.4 文档排序

`list_documents()` 的排序规则：

1. `README.md` 永远优先；
2. 其余按 `sort_order ASC, id ASC`。

文档列表接口不返回正文，只返回元数据和一个 `size` 字段。正文只在读取单篇文档或导出时返回。

## 6. 配置与启动

### 6.1 配置优先级

```text
环境变量 > TOML 配置文件 > 内置默认值
```

环境变量：

| 变量 | 作用 |
| --- | --- |
| `LAN_NAV_HOST` | 监听地址，默认 `0.0.0.0` |
| `LAN_NAV_PORT` | 监听端口，默认 `50001` |
| `LAN_NAV_DATA` | 数据目录，数据库为 `<目录>/nav.db` |
| `LAN_NAV_DB` | 直接指定数据库文件，优先级高于 `LAN_NAV_DATA` |
| `LAN_NAV_CONFIG` | 指定 TOML 配置文件 |

默认路径：

- 数据目录：`$XDG_DATA_HOME/lan-nav`，未设置时为 `~/.local/share/lan-nav`；
- 数据库：`<数据目录>/nav.db`；
- 配置文件：`$XDG_CONFIG_HOME/lan-nav/config.toml`，未设置时为
  `~/.config/lan-nav/config.toml`。

配置文件示例：

```toml
[server]
host = "0.0.0.0"
port = 50001

[database]
path = "~/.local/share/lan-nav/nav.db"
```

`~` 会通过 `Path.expanduser()` 展开。

### 6.2 启动方式

| 方式 | 热重载 | 读取 TOML | 环境校验 |
| --- | --- | --- | --- |
| `./run.sh` | 否 | 会被导出的环境变量覆盖 | 有 |
| `./run-dev.sh` | 是 | 会被导出的环境变量覆盖 | 仅检查 uv |
| `uv run python -m app` | 否 | 是 | 无 |

`run.sh` 会检查：

1. `uv` 是否存在；
2. `uv python find '>=3.10'` 是否能找到解释器；
3. Python 是否可执行、版本是否满足要求；
4. `sqlite3`、`ssl` 模块是否可导入；
5. 数据目录是否可创建、可写；
6. 端口是否可以绑定；
7. `uv sync --frozen` 是否成功；
8. `.venv/bin/python` 是否存在。

检查通过后，脚本导出 `LAN_NAV_HOST`、`LAN_NAV_PORT`、`LAN_NAV_DATA`，并执行：

```bash
.venv/bin/python -m app
```

`run-dev.sh` 使用 `uv run uvicorn app.main:app --reload`，适合开发调试。

## 7. HTTP API

统一前缀 `/api`，请求和响应均为 JSON。Swagger/ReDoc UI 依赖外部 CDN，因此未启用；
OpenAPI 描述可访问：

```text
GET /api/openapi.json
```

### 7.1 端点列表

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查、版本、分组/链接数量 |
| GET | `/api/tree` | 完整分组树、链接、文档计数 |
| GET | `/api/search?q=关键词&limit=200` | 搜索全部链接的标题/URL/描述 |
| POST | `/api/check-links` | 批量检测连通性，单次最多 50 条 |
| POST | `/api/groups` | 新建分组 |
| PATCH | `/api/groups/{id}` | 修改名称、上级分组或排序 |
| DELETE | `/api/groups/{id}?cascade=true` | 删除分组；非空分组必须带 `cascade=true` |
| POST | `/api/links` | 新建链接 |
| PATCH | `/api/links/{id}` | 修改链接字段，包括 `group_id` |
| POST | `/api/links/{id}/move` | 在/到分组内移动排序 |
| DELETE | `/api/links/{id}` | 删除链接 |
| GET | `/api/groups/{id}/documents` | 列出分组的文档（不含正文） |
| POST | `/api/groups/{id}/documents` | 新建文档 |
| GET | `/api/documents/{id}` | 读取文档正文和渲染后的 HTML |
| PATCH | `/api/documents/{id}` | 修改文档名或正文 |
| DELETE | `/api/documents/{id}` | 删除文档 |
| GET | `/api/export` | 导出完整数据 |
| POST | `/api/import` | 导入 JSON，覆盖现有数据并先备份 |

### 7.2 分组与链接

新建分组：

```json
{"name": "内部系统", "parent_id": null, "sort_order": 0}
```

修改分组：

```json
{"name": "运维监控", "parent_id": 2, "sort_order": 10}
```

新建链接：

```json
{
  "group_id": 1,
  "title": "NAS",
  "url": "http://192.168.1.20:5000",
  "description": "共享文件夹和备份",
  "icon": "",
  "sort_order": 0
}
```

链接移动排序：

```json
{
  "group_id": 3,
  "before_id": 12
}
```

`before_id`、`after_id`、`position` 三选一；不传时追加到目标分组末尾。

### 7.3 分组文档

列出文档：

```json
{
  "group_id": 84,
  "documents": [
    {
      "id": 1,
      "group_id": 84,
      "name": "README.md",
      "sort_order": 0,
      "size": 128,
      "created_at": "2026-11-08T12:00:00Z",
      "updated_at": "2026-11-08T12:00:00Z"
    }
  ]
}
```

读取单篇文档时，在元数据基础上增加：

- `content`：原始 Markdown；
- `html`：服务端渲染后的 HTML。

新建文档：

```json
{"name": "notes", "content": "# 备忘", "sort_order": 0}
```

规则：

- `name` 默认为 `README.md`；
- 没有 `.md` 后缀会自动补上；
- 名称不能包含 `/`、`\` 等路径分隔符；
- 名称上限 120 字；
- 正文上限 20 万字符；
- 同一分组内重名返回 `409`。

`PATCH /api/documents/{id}` 只修改传入的字段，未传字段保持不变。

### 7.4 导入与导出

导出格式：

```json
{
  "format": "lan-nav-export",
  "version": 1,
  "app_version": "1.0.0",
  "exported_at": "2026-11-11T05:00:00Z",
  "groups": [],
  "links": [],
  "documents": []
}
```

`groups`、`links` 是扁平数组，通过 `parent_id` / `group_id` 关联。`documents` 包含正文。

导入流程：

1. 校验整个 JSON 结构、字段类型、URL、分组引用和文档名；
2. 限制最多 5000 个分组、20000 条链接、20000 篇文档；
3. 在数据目录 `backups/` 下创建当前数据库的在线备份；
4. 在一个事务中删除旧文档、旧链接、旧分组；
5. 重新插入分组、链接和文档，并建立旧 ID 到新 ID 的映射；
6. 返回 `{ok, groups, links, documents, backup}`。

旧的导出文件如果没有 `documents` 字段，仍可导入，视为没有文档。

### 7.5 删除分组

非空分组默认返回 `409`。带 `cascade=true` 时删除整个子树，并返回：

```json
{
  "ok": true,
  "deleted_groups": 3,
  "deleted_links": 5,
  "deleted_documents": 2
}
```

### 7.6 错误处理

- `400`：业务校验失败（名称为空、协议不支持、分组移动形成循环、文档名非法等）；
- `404`：分组/链接/文档不存在；
- `409`：删除非空分组未提供 `cascade=true`，或同一分组内文档重名；
- `422`：请求体结构或字段类型不合法。

`detail` 使用中文说明。请求校验错误由统一异常处理器转成：

```json
{
  "detail": "请求参数不合法（field）",
  "errors": []
}
```

### 7.7 安全响应头

中间件为所有响应设置：

```text
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: no-referrer
```

`/api/*` 额外设置：

```text
Cache-Control: no-store
```

项目没有 CORS 配置，也没有 Cookie 会话。

## 8. 链接连通性检测

### 8.1 基本流程

1. 前端把链接 ID 分批发送到 `POST /api/check-links`，每批 15 条；
2. 服务端从数据库读取这些链接的 URL；
3. 按 URL 去重，先查进程内缓存；
4. 未命中的 URL 进入异步检测池；
5. 结果按 URL 写回缓存，再映射回每个链接 ID；
6. 前端按 ID 更新卡片徽章。

检测结果不写入数据库，也不会触发导入备份。

### 8.2 参数与限制

| 参数 | 值 |
| --- | --- |
| 单次接口最多 ID 数 | 50 |
| 服务端最大并发 | 16 |
| 单次请求超时 | 2.5 秒 |
| 单链接总超时 | 3.0 秒 |
| 最大重定向次数 | 3 |
| 慢响应阈值 | 800 ms |
| 缓存 TTL | 60 秒 |
| 缓存最大条目 | 4096 |
| 前端每批数量 | 15 |
| 自动检测上限 | 当前列表前 20 条未检测链接 |

### 8.3 状态判定

- `2xx / 3xx`：`status=ok`；延迟 ≥ 800 ms 时 `status=slow`；
- `4xx`：`status=error`、`reachable=true`，原因类似 `HTTP 404（可达但异常）`；
- `5xx`：`status=error`、`reachable=true`，原因类似 `HTTP 500（服务端错误）`；
- 其他异常状态码：`status=error`、`reachable=true`；
- DNS 失败、连接拒绝、连接超时、证书失败、重定向过多、非法协议等：
  `status=error`、`reachable=false`。

返回示例：

```json
{
  "count": 2,
  "cached": 0,
  "results": [
    {
      "id": 1,
      "ok": true,
      "status": "ok",
      "reachable": true,
      "latency_ms": 23,
      "http_status": 200,
      "reason": null,
      "checked_at": "2026-10-29T05:40:00Z",
      "tls_insecure": false,
      "cached": false
    },
    {
      "id": 3,
      "ok": false,
      "status": "error",
      "reachable": false,
      "latency_ms": 2504,
      "http_status": null,
      "reason": "请求超时",
      "checked_at": "2026-10-29T05:40:02Z",
      "tls_insecure": false,
      "cached": false
    }
  ]
}
```

### 8.4 证书降级

- 主请求使用正常证书校验；
- 如果错误被识别为证书问题，且总超时内还有剩余时间，则使用
  `verify=False` 重试一次；
- 重试成功时返回 `tls_insecure=true`，原因注明“证书校验未通过，已降级重试”；
- 这不是忽略所有 TLS 错误，只在证书校验失败时降级。

### 8.5 请求特征

- 使用 `GET` 并流式读取，只读取响应头后关闭连接；
- `trust_env=False`，不读取系统代理环境变量；
- 不携带浏览器 Cookie、LocalStorage 或登录态；
- 只支持 `http` / `https`；
- 检测由运行服务的机器发起，因此它看到的是服务端所在网络的连通性。

## 9. Markdown 渲染

服务端使用 markdown-it-py：

```python
MarkdownIt("commonmark", {"html": False, "linkify": True})
    .enable("table")
    .enable("strikethrough")
```

- 关闭内联 HTML，`<script>` 等标签会作为文本转义；
- 开启自动链接、表格和删除线；
- 文档列表不返回正文，减少树接口体积；
- 正文上限 20 万字符，在 API 层校验；
- 渲染结果直接返回给前端，前端使用 `innerHTML` 展示服务端结果；
- 没有前端 Markdown 解析器，也没有外部 CDN。

## 10. 前端实现

### 10.1 状态与渲染

`app/static/app.js` 使用一个内存 `state` 对象保存：

- 当前分组树、选中分组、搜索词；
- 展开状态；
- 当前列表、当前视图类型；
- 链接检测结果、批量检测进度；
- 文档列表、当前文档、编辑状态；
- 拖动状态和点击抑制标记。

启动流程：

1. `DOMContentLoaded` 后缓存 DOM 引用；
2. 读取浏览器偏好；
3. 请求 `/api/tree`；
4. 请求 `/api/health` 更新底栏状态；
5. 任何写操作成功后重新拉取树并重绘。

没有 URL 路由，刷新页面会回到“全部链接”。

### 10.2 卡片点击

卡片本身就是唯一一个原生 `<a target="_blank">`，再用 `::after` 拉伸铺满整张卡片
（stretched link），不使用 JS `window.open()` 或合成 `click()`：

```html
<a class="link-body" href="..." target="_blank" rel="noopener noreferrer">…</a>
```

```css
.link-body::after { content: ""; position: absolute; inset: 0; z-index: 1; }
```

- 浏览器原生导航，不受弹窗拦截策略影响，Cmd/Ctrl/Shift 点击和右键菜单也保持原生语义；
- 卡片右上角操作按钮默认 `visibility: hidden` + `pointer-events: none`，只有卡片
  `:hover` / `:focus-within` 时才显示并可点。`visibility` 与透明度同时切换，
  不存在“看得见之前已经能点”的窗口，避免不可见按钮抢走卡片链接的点击
  （Safari 的 `:hover` 更新较晚时尤其明显）；
- 检测徽章通过更高的 `z-index` 和 `pointer-events: auto` 保持独立可点；
- 右上角最左侧的复制按钮把 `link.url` 写入剪贴板。优先使用
  `navigator.clipboard.writeText()`；局域网通常以 `http://IP` 访问，属于非安全上下文，
  该 API 不可用，此时退回 `textarea + document.execCommand("copy")`，兜底在用户手势内
  同步执行，成功后用 toast 提示；
- 图片和锚点设置 `draggable=false`，避免浏览器原生拖拽抢占手势；
- 极少数落在卡片 1px 边框或圆角边缘的点击由 `#linkGrid` 的点击兜底处理：
  目标在网格上时按坐标找回卡片，触发卡片内原生链接的 `click()`，避免边缘静默无响应；
- Safari 在指针捕获等异常状态下偶尔会把 `click` 的 target 退化成 `<body>`。
  `document` 上另有一个兜底：只有 target 是 `<body>/<html>` 且按坐标仍落在卡片上时，
  才触发对应原生链接，正常点击不会重复打开；
- 长按拖动期间会抑制随后的 `click`，避免松手时误打开链接。

### 10.3 链接弹窗

- 链接弹窗点击遮罩不会关闭；
- `Esc` 不会关闭链接弹窗；
- 只能通过“取消”、右上角关闭按钮或保存成功关闭；
- 校验错误和 API 错误显示在弹窗内部、保存按钮上方的 `#linkFormError` 中；
- 全局 toast 位于 `dialog` 之外，不能用于弹窗内错误提示，否则会被顶层遮罩盖住。

### 10.4 长按拖动排序

只在具体分组页面启用，且只响应鼠标左键：

1. `pointerdown` 启动 450 ms 定时器；
2. 定时器触发后只进入“预备拖动”（armed）状态，不改变界面；
3. 预备状态下指针移动超过 8 px 才真正进入拖动；预备前就移动，或松开时始终没有移动，
   都按普通点击处理；
4. 创建占位块和拖动幽灵，隐藏原卡片；
5. 在 `pointermove` 中根据指针位置移动占位块；
6. 靠近滚动区域边缘时自动滚动；
7. `pointerup` 计算新的前后 ID，调用
   `POST /api/links/{id}/move`；
8. 保存成功后重新拉取树。

取消方式：

- 按 `Esc`；
- 窗口失焦；
- 页面切到后台、从 bfcache 恢复或窗口重新获得焦点；
- 指针取消事件。

拖动结束后 250 ms 内抑制卡片区域内的点击，避免松手触发卡片导航。抑制使用
`Date.now()` 时间戳而不是布尔值 + `setTimeout`：Safari 在标签页挂起/后台时会推迟
定时器，布尔值可能残留到用户回来后的第一次点击，把正常跳转吞掉。

页面长时间放置后，Safari 可能挂起 WebContent 进程，恢复时补发定时器和输入事件。
为此拖动逻辑有两道保护：

- 长按定时器如果比 `pointerdown` 晚 700 ms 以上才执行，说明页面刚被节流，
  不再进入预备拖动；
- `pointerup` 时用输入事件自带的时间戳核对真实按键时长，短于 450 ms 的“拖动”
  视为被延迟处理普通点击：撤销拖动、不抑制 `click`，让链接照常打开。

`pointermove` 还会检查 `event.buttons`：按钮已经松开（例如丢掉了 `pointerup`）
就不再开启拖动；拖动中丢失 `pointerup` 则按最后位置结束，避免幽灵卡片残留。
`visibilitychange`、`pageshow`、`focus`、`blur` 都会调用
`resetInteractionState()` 清掉残留状态，且这些生命周期清理不会抑制点击。

只按住、不移动指针不会进入拖动状态，长按后直接松手仍然会正常打开链接。
“全部链接”和搜索结果页不启用拖动，避免跨分组歧义。

### 10.5 文档栏

- 顶部“文档”开关状态保存在 `localStorage`，默认关闭；
- 只有具体分组页面可以显示文档栏；
- 布局使用 `#contentSplit` 的左右分栏，左侧链接、右侧文档；
- 关闭开关后链接恢复整宽；
- 进入分组时优先加载 `README.md`；
- 文档树图标来自 `/api/tree` 中的 `direct_document_count`；
- 文档请求带自增 `requestId`，切换分组后旧响应会被丢弃，避免竞态覆盖；
- 编辑时 `Ctrl/Cmd + Enter` 保存，`Esc` 取消。

### 10.6 浏览器本地偏好

| key | 内容 |
| --- | --- |
| `lannav.expanded` | 侧边栏展开的分组 ID 数组 |
| `lannav.autoCheck` | 是否开启自动检测 |
| `lannav.showDocs` | 是否显示文档栏 |

这些都是界面偏好，不包含用户身份。禁用 `localStorage` 时只在当前页面会话内生效。

### 10.7 响应式与主题

- 桌面端固定侧栏；
- 窄屏下侧栏变为抽屉，通过遮罩关闭；
- 使用 `prefers-color-scheme` 适配浅色/深色模式；
- 不依赖外部字体、图标库或 CDN；图标使用内联 SVG symbol。

## 11. 备份、恢复与导入

### 11.1 在线备份

`app/backup.py` 使用 SQLite 的在线备份 API：

```python
source.backup(destination)
```

备份默认写入数据库同级的 `backups/`，文件名为：

```text
lan-nav-YYYYMMDD-HHMMSSZ.db
```

备份期间服务可以继续运行。

### 11.2 恢复

恢复前会先备份当前数据库，再替换目标文件。恢复应停止服务，避免连接仍持有旧文件。
命令：

```bash
uv run python -m app.backup restore \
  ~/.local/share/lan-nav/nav.db \
  ~/.local/share/lan-nav/backups/lan-nav-YYYYMMDD-HHMMSSZ.db
```

### 11.3 导入事务

导入先校验、再备份、再在单个事务中删除和插入。这样即使导入数据有问题，也不会只写入一半；
但导入仍然是**覆盖**语义，不会合并现有数据。

## 12. 测试

运行：

```bash
uv run pytest
```

当前共 **25 个测试通过**，覆盖：

- 三层分组创建与树计数；
- 分组移动防环、级联删除；
- 链接 CRUD、URL 校验、搜索、排序；
- 导入导出及导入前备份；
- 错误文案和静态页面；
- 配置路径优先级；
- 文档 CRUD、Markdown 渲染、XSS 转义；
- 文档名称校验/重名、级联删除、树中文档计数；
- 文档导出导入；
- 连通性检测的正常/慢响应/4xx/5xx/重定向/重定向过多/连接拒绝/DNS 失败/超时/
  非法协议/批量上限/缓存 TTL/有界并发/不写数据库。

测试使用 FastAPI `TestClient` 和临时数据库，不依赖外部网络服务。

## 13. 已知限制

- 没有登录、权限和审计；任何能访问端口的人都可以编辑；
- 没有实时推送；多人修改后需要刷新页面；
- 没有冲突合并，后保存的字段覆盖先保存的字段；
- SQLite 单机写入，不适合大规模高并发；
- 检测缓存只在当前进程内存中，重启清空，多 worker 不共享；
- 检测结果不持久化；
- 需要认证的目标页面通常返回 401/403，只显示“可达但异常”；
- 只检查 HTTP 响应，不验证页面内容和前端资源；
- Markdown 不支持内联 HTML；
- 搜索只搜索链接，不搜索文档正文；
- 没有 URL 路由，刷新页面回到全部链接；
- 拖动排序只在具体分组页面启用；
- 应用本身不安装 systemd 服务，开机自启需要用户自行配置；
- 没有 CORS、Cookie 会话或 CSRF token，因为产品本身没有登录态。

## 14. 安全模型

lan-nav 的安全边界是**可信局域网**，不是公网：

- 无认证、无授权、无用户隔离；
- 任何访问者都可以读取和修改全部分组、链接和文档；
- 不要将端口直接暴露到公网；
- 如果必须跨不可信网络访问，应放在带认证和 TLS 的反向代理后面；
- Markdown 禁用内联 HTML，降低存储型 XSS 风险；
- 前端不使用外部 CDN，减少供应链和隐私风险；
- 链接检测器可以请求任意 `http`/`https` 地址，包括内网地址，这是产品功能的一部分；
  如果服务被暴露到不可信网络，检测接口可能被用来探测内网；
- 安全响应头提供基础的点击劫持、MIME 嗅探和 Referer 防护；
- 重要数据应定期导出 JSON 或备份数据库。

## 15. 相关文档

- [部署与使用说明](USER-GUIDE.md)
- [项目 README](../README.md)
- [Apache License 2.0](../LICENSE)
