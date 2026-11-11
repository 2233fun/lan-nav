# 邻页 · 部署与使用说明

本文面向第一次部署和使用 lan-nav 的人。照着下面的步骤操作，就可以在自己的机器上启动服务，
并让同一局域网内的其他设备访问。

> 截图和示例中的分组、链接均为虚构演示数据。你自己的实例首次启动时是空数据库，需要自行添加内容。

## 1. 适用场景

lan-nav 是一个供局域网内部共享的网址导航工具：

- 分组可以任意层级嵌套；
- 链接可以增删改、搜索和排序；
- 每个分组可以放多篇 Markdown 文档；
- 局域网内的用户直接用浏览器打开即可查看和编辑；
- **没有登录功能**，只适合可信的内部网络。

## 2. 环境要求

推荐使用 Linux。macOS 也可以运行启动脚本；Windows 建议使用 WSL2。

需要：

| 依赖 | 要求 | 说明 |
| --- | --- | --- |
| Python | 3.10 或更高 | `run.sh` 会自动检查 |
| uv | 任意较新版本 | 用于创建虚拟环境和安装依赖 |
| 网络 | 首次启动需要 | 从 Python 包索引下载依赖 |
| 磁盘 | 少量空间 | 数据库和文档都很小 |

### 没有 Python 怎么办？

`run.sh` 会先检查 Python。如果没有，可以让 uv 安装一个：

```bash
uv python install 3.12
```

### 没有 uv 怎么办？

任选一种方式安装：

```bash
# 官方安装脚本
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或者使用 pipx
pipx install uv
```

安装后重新打开终端，确认：

```bash
uv --version
```

## 3. 获取代码

```bash
git clone <你的仓库地址> lan-nav
cd lan-nav
```

如果拿到的是压缩包，解压后进入目录即可。然后确保启动脚本可执行：

```bash
chmod +x run.sh run-dev.sh
```

## 4. 首次启动

```bash
./run.sh
```

`run.sh` 会依次做这些检查：

1. 是否安装了 `uv`；
2. 是否找得到 Python 3.10+，以及 `sqlite3`、`ssl` 模块是否可用；
3. 数据目录能否创建和写入；
4. 端口是否被其他程序占用；
5. 使用 `uv sync --frozen` 安装锁定版本的依赖；
6. 以**非热重载**模式启动服务。

启动成功后会打印类似内容：

```text
==> LanNav 正在启动（生产模式，无热重载）
    本机访问：http://127.0.0.1:50001/
    局域网访问：http://192.168.1.10:50001/
    数据目录：~/.local/share/lan-nav（数据库 nav.db）
    版本：1.0.0
    停止服务：按 Ctrl+C
```

在运行终端按 `Ctrl+C` 即可停止服务。

### 开发时使用热重载

```bash
./run-dev.sh
```

这个脚本会启用 Uvicorn 的 `--reload`，修改代码后自动重启，适合开发调试。

## 5. 访问服务

### 本机访问

```text
http://127.0.0.1:50001/
```

### 局域网访问

先查看本机局域网 IP：

```bash
hostname -I
```

然后让同一网段的设备打开：

```text
http://<本机局域网IP>:50001/
```

如果其他设备打不开，依次检查：

1. 服务是否监听 `0.0.0.0:50001`；
2. 本机防火墙是否放行端口；
3. 路由器或 AP 是否开启了“客户端隔离/AP 隔离”；
4. 两台设备是否在同一网段；
5. 云主机或上游防火墙的安全组是否放行。

使用 UFW 时放行端口：

```bash
sudo ufw status
sudo ufw allow 50001/tcp
```

换端口时，放行规则也要同步修改。

## 6. 日常使用

### 分组

- 右上角“新建分组”创建顶级分组；
- 选中分组后，页面上的“子分组”可以在当前分组下继续创建；
- 分组支持任意深度；
- 悬停分组或选中分组后，点击编辑图标可以改名、移动到其他分组或调整排序；
- 删除分组时，确认框会显示将一起删除的子分组、链接和文档数量；确认后级联删除。

### 链接

- 顶部“新建链接”或分组页内的“添加链接”；
- 网址可以写完整地址，也可以省略 `http://`；
- 每条链接可以填写标题、描述、图标地址和排序值；
- 卡片悬停后可以上移/下移；
- 在具体分组页面，鼠标左键长按卡片约 0.45 秒后拖动，可以调整顺序；短按或按住不动后松手仍然是打开链接；
- “全部链接”和搜索结果页不启用拖动排序，避免跨分组歧义。

### 打开链接

点击卡片任意位置即可在新标签页打开。检测徽章、编辑、删除和排序按钮保持各自功能。
卡片本身就是浏览器原生链接，Safari 下也不会被当成弹窗拦截；右上角操作按钮只在悬停
或键盘聚焦后出现并可点，不会在看不见的时候抢走卡片链接的点击。

### 搜索

顶部搜索框会实时搜索全部链接的标题、网址和描述，不搜索 Markdown 文档正文。

### 分组文档

- 顶部“文档”开关控制是否显示文档栏，默认关闭；
- 打开后，具体分组页面左侧是链接，右侧是文档；
- 默认加载 `README.md`；
- 可以新建、编辑、删除文档，文档名会自动补 `.md`；
- 同一分组内文档名不能重复，单篇正文最多 20 万字符；
- 文档由服务端渲染 Markdown，禁用内联 HTML；
- 有文档的分组会在左侧分组树显示文档图标，点击可直接打开文档栏；
- 删除分组会级联删除其中的文档。

### 连通性检测

- 卡片右下角的状态徽章可以检测单条链接；
- 页面标题右侧的“检测全部”检测当前列表中的全部链接，可中途停止；
- “自动检测”默认开启，只检测当前列表前 20 条尚未检测的链接；
- 检测从运行服务的机器发起真实 HTTP 请求，不携带浏览器登录态；
- 需要认证的页面可能显示 401/403，这属于“可达但异常”；
- 检测结果不写入数据库，缓存 60 秒。

### 导入与导出

- 侧栏底部“导出”下载完整 JSON，包含分组、链接和文档；
- “导入”会用 JSON 覆盖当前数据；
- 导入前服务端会自动备份当前数据库到 `<数据目录>/backups/`；
- 导入确认框会显示将要导入的分组、链接和文档数量。

> 重要数据请定期导出 JSON 或备份数据库。导入是覆盖操作，不是合并。

## 7. 配置

### 命令行选项

`run.sh` 和 `run-dev.sh` 支持相同选项：

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

LAN_NAV_PORT=8090 ./run.sh
```

### 数据位置

默认数据目录：

```text
~/.local/share/lan-nav/
├── nav.db
└── backups/
    └── lan-nav-YYYYMMDD-HHMMSSZ.db
```

`nav.db` 是 SQLite 主数据库，分组、链接和文档都在里面。

如果设置了 `XDG_DATA_HOME`，默认目录会变成 `$XDG_DATA_HOME/lan-nav/`。

### 可选配置文件

默认配置文件是 `~/.config/lan-nav/config.toml`，也可以设置 `LAN_NAV_CONFIG` 指向别处：

```toml
[server]
host = "0.0.0.0"
port = 50001

[database]
path = "~/.local/share/lan-nav/nav.db"
```

配置优先级：

```text
环境变量 > TOML 配置文件 > 内置默认值
```

注意：`run.sh` 和 `run-dev.sh` 会把命令行参数/环境变量导出给应用，因此使用这两个脚本时，
环境变量优先于配置文件。若希望完全按配置文件启动，请使用：

```bash
uv run python -m app
```

## 8. 开机自启（systemd）

项目不会自动安装系统服务。下面的示例适用于 Linux 的 systemd 用户服务。

先手动运行一次 `./run.sh`，确认服务能正常启动，并生成 `.venv`。

创建 `~/.config/systemd/user/lan-nav.service`：

```ini
[Unit]
Description=LanNav 局域网网址导航
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/lan-nav
Environment=LAN_NAV_DATA=%h/.local/share/lan-nav
ExecStart=%h/lan-nav/.venv/bin/python -m app
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

如果你的项目不在 `~/lan-nav`，把 `WorkingDirectory` 和 `ExecStart` 里的路径改成实际位置。
`%h` 表示当前用户的家目录。

启用服务：

```bash
mkdir -p ~/.config/systemd/user
systemctl --user daemon-reload
systemctl --user enable --now lan-nav
systemctl --user status lan-nav
```

让用户未登录时也能启动：

```bash
loginctl enable-linger "$USER"
```

查看日志：

```bash
journalctl --user -u lan-nav -f
```

停止或禁用：

```bash
systemctl --user stop lan-nav
systemctl --user disable lan-nav
```

## 9. 备份、恢复、升级与卸载

### 导出 JSON

在页面侧栏点击“导出”，或在命令行请求：

```bash
curl -s http://127.0.0.1:50001/api/export > lan-nav-backup.json
```

### 备份数据库

服务运行时也可以做一致性备份：

```bash
cd ~/lan-nav
uv run python -m app.backup backup ~/.local/share/lan-nav/nav.db
```

备份文件会写到数据目录下的 `backups/`。

### 恢复数据库

先停止服务，再执行：

```bash
systemctl --user stop lan-nav   # 如果使用 systemd
cd ~/lan-nav
uv run python -m app.backup restore \
  ~/.local/share/lan-nav/nav.db \
  ~/.local/share/lan-nav/backups/lan-nav-YYYYMMDD-HHMMSSZ.db
./run.sh
```

恢复前会自动备份当前数据库。

### 升级

```bash
systemctl --user stop lan-nav   # 如果使用 systemd
cd ~/lan-nav
git pull
uv sync --frozen
./run.sh
```

如果启动方式使用 systemd，升级后再执行：

```bash
systemctl --user start lan-nav
```

### 停止与卸载

```bash
systemctl --user disable --now lan-nav
rm -f ~/.config/systemd/user/lan-nav.service
systemctl --user daemon-reload
```

确认已经导出或备份后，再删除项目目录和数据目录：

```bash
rm -rf ~/lan-nav
rm -rf ~/.local/share/lan-nav
```

**删除数据目录会永久丢失分组、链接和文档，请务必先备份。**

## 10. 常见问题

### 提示未检测到 uv

按第 2 节安装 uv，并确认 `uv --version` 可用。如果 uv 安装在 `~/.local/bin`，
重新登录或把该目录加入 `PATH`。

### 提示未检测到 Python 3.10+

让 uv 安装一个 Python：

```bash
uv python install 3.12
```

然后重新执行 `./run.sh`。

### 提示端口被占用

查看占用：

```bash
ss -ltnp '( sport = :50001 )'
```

换一个端口：

```bash
./run.sh --port 8090
```

### 其他设备访问不了

检查防火墙、AP 隔离、网段和安全组。先用本机访问
`http://127.0.0.1:50001/` 确认服务本身正常。

### 连通性检测显示超时

检测是从运行服务的机器发起真实 HTTP 请求。局域网地址不可达、DNS 解析失败、
目标站点拒绝连接或超时都会显示失败。检测失败只影响徽章，不影响链接本身。

### 图标不显示

页面会优先请求站点的 `/favicon.ico`。局域网地址、没有图标的站点或禁止访问的站点会加载失败，
此时显示首字彩色占位块。可以在编辑链接时填写“图标地址”指定可用图片。

### 多人同时编辑会怎样

SQLite 使用 WAL 和事务，写操作会安全串行化，不会损坏数据库。但没有实时推送或冲突合并，
其他人的修改需要刷新页面后才能看到；后保存的字段会覆盖先保存的字段。

### 数据存在哪里

默认是 `~/.local/share/lan-nav/nav.db`。如果用过 `--data`、`LAN_NAV_DATA` 或配置文件，
按对应位置查找；`run.sh` 启动时会打印实际数据目录。

### 为什么没有登录

这是产品的明确设计：任何能访问页面的局域网用户都可以查看和编辑。不要直接把端口暴露到公网。
如果必须跨不可信网络使用，请放在带认证的反向代理后面。

## 11. 安全说明

- lan-nav 没有账号、密码和权限控制；
- 任何能访问服务端口的人都可以查看和修改数据；
- 只建议在可信局域网中使用；
- 不要直接暴露到公网；
- 重要数据定期备份；
- Markdown 渲染禁用内联 HTML，但文档内容仍应按可信内部内容对待。

## 12. 更多文档

- 项目介绍与快速开始：[README.md](../README.md)
- 技术实现细节：[TECHNICAL.md](TECHNICAL.md)
- 许可证：[LICENSE](../LICENSE)
