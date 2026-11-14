# 邻页 · 局域网网址导航（lan-nav）

一个供局域网内部共享使用的网址导航工具。分组可以任意层级嵌套，链接可以随意增删改；
同一局域网内的人用浏览器打开就能查看和编辑，**没有登录墙**。

后端是 Python + FastAPI + SQLite，前端是原生 HTML/CSS/JavaScript，无构建步骤、无外部 CDN。

![桌面端界面](docs/screenshot.png)

## 功能

- 无限层级的树形分组，支持新建、重命名、移动、排序和折叠。
- 链接支持标题、URL、描述、自定义图标和排序；分组页支持长按拖动排序。
- 顶部实时搜索全部链接的标题、网址和描述。
- 每个分组可以放多篇 Markdown 文档，支持查看、新建、编辑和删除。
- 文档默认隐藏，可通过顶部“文档”开关打开；有文档的分组在树中显示文档图标。
- 链接卡片显示连通性状态，支持单条检测、检测全部和自动检测。
- 整站 JSON 导出/导入；导入前自动备份 SQLite 数据库。
- 桌面和手机浏览器自适应，支持系统浅色/深色模式。
- 服务端使用有界并发检测，结果缓存 60 秒，页面首屏不等待检测。
- SQLite 开启 WAL、外键和 busy timeout，适合局域网内多人同时读写。

## 快速开始

### 1. 准备环境

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。没有 uv 时：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

没有 Python 时，可以让 uv 安装：

```bash
uv python install 3.12
```

### 2. 获取并启动

```bash
git clone <仓库地址> lan-nav
cd lan-nav
./run.sh
```

`run.sh` 会先检查 uv、Python、数据目录和端口，再用 `uv sync --frozen` 安装依赖并以生产模式启动。
首次运行需要联网。

开发时使用热重载：

```bash
./run-dev.sh
```

### 3. 打开页面

- 本机：<http://127.0.0.1:50001/>
- 局域网：`http://<本机局域网IP>:50001/`

默认监听 `0.0.0.0:50001`。首次启动是空数据库，截图中的内容为虚构演示数据。

## 常用配置

| 选项 | 环境变量 | 默认值 |
| --- | --- | --- |
| `--host` | `LAN_NAV_HOST` | `0.0.0.0` |
| `--port` | `LAN_NAV_PORT` | `50001` |
| `--data` | `LAN_NAV_DATA` | `~/.local/share/lan-nav` |

示例：

```bash
./run.sh --port 8090
./run.sh --host 127.0.0.1 --port 8081
./run.sh --data /srv/lan-nav-data
```

也可以使用配置文件 `~/.config/lan-nav/config.toml`，详见
[部署与使用说明](docs/USER-GUIDE.md#7-配置)。

## 数据与备份

默认数据目录：

```text
~/.local/share/lan-nav/
├── nav.db
└── backups/
    └── lan-nav-YYYYMMDD-HHMMSSZ.db
```

`nav.db` 是 SQLite 主数据库，分组、链接和文档都在里面。侧栏“导出”可以下载完整 JSON；
导入会覆盖现有数据，并在服务端先自动备份数据库。

## 文档

- [部署与使用说明](docs/USER-GUIDE.md)：安装、启动、局域网访问、systemd 开机自启、备份恢复、
  日常使用和常见问题。
- [技术说明](docs/TECHNICAL.md)：架构、数据模型、API、链接检测、Markdown、前端交互和测试。
- [更新日志](CHANGELOG.md)：版本变更记录。

## 技术栈

- Python ≥ 3.10
- FastAPI、Uvicorn、HTTPX、markdown-it-py
- SQLite（WAL 模式）
- 原生 HTML / CSS / JavaScript
- uv 管理环境和依赖
- pytest

## 开发与测试

```bash
# 安装依赖
uv sync

# 开发模式（热重载）
./run-dev.sh

# 运行测试
uv run pytest
```

当前测试覆盖分组树、链接 CRUD、搜索、排序、导入导出、文档、Markdown 转义和链接检测等，
共 **26 个测试通过**。

## 安全说明

lan-nav **没有登录和权限控制**，任何能访问端口的人都可以查看和编辑数据。它只适合可信局域网，
不要直接暴露到公网。如果必须跨不可信网络使用，请放在带认证的反向代理后面。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)，版权归 lan-nav contributors 所有。
