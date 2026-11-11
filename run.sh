#!/usr/bin/env bash
# lan-nav 生产启动脚本：校验运行环境、安装依赖并以非热重载模式启动服务。
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd -P)"

HOST="${LAN_NAV_HOST:-0.0.0.0}"
PORT="${LAN_NAV_PORT:-50001}"
DATA_DIR="${LAN_NAV_DATA:-$HOME/.local/share/lan-nav}"

usage() {
  cat <<'EOF'
用法：./run.sh [选项]

选项：
  --host <地址>    监听地址，默认 0.0.0.0
  --port <端口>    监听端口，默认 50001
  --data <目录>    数据目录，默认 ~/.local/share/lan-nav
  -h, --help       显示本帮助

环境变量：
  LAN_NAV_HOST / LAN_NAV_PORT / LAN_NAV_DATA 与上面选项等价。
  数据库固定为 <数据目录>/nav.db，可用 LAN_NAV_DB 单独覆盖数据库路径。

说明：
  本脚本用于部署和日常运行，不启用热重载。开发时请使用 ./run-dev.sh。
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host)
      [ $# -ge 2 ] || { echo "错误：--host 缺少参数" >&2; exit 2; }
      HOST="$2"; shift 2 ;;
    --host=*) HOST="${1#*=}"; shift ;;
    --port)
      [ $# -ge 2 ] || { echo "错误：--port 缺少参数" >&2; exit 2; }
      PORT="$2"; shift 2 ;;
    --port=*) PORT="${1#*=}"; shift ;;
    --data)
      [ $# -ge 2 ] || { echo "错误：--data 缺少参数" >&2; exit 2; }
      DATA_DIR="$2"; shift 2 ;;
    --data=*) DATA_DIR="${1#*=}"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "错误：未知参数 $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

fail() {
  echo "错误：$1" >&2
  shift
  for line in "$@"; do
    echo "  $line" >&2
  done
  exit 1
}

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  fail "端口必须是 1-65535 之间的整数。"
fi

case "$DATA_DIR" in
  "~") DATA_DIR="$HOME" ;;
  "~/"*) DATA_DIR="$HOME/${DATA_DIR#~/}" ;;
esac

[ -f "$PROJECT_DIR/pyproject.toml" ] || fail "未找到 pyproject.toml，请在 lan-nav 项目目录中运行本脚本。"
[ -f "$PROJECT_DIR/uv.lock" ] || fail "未找到 uv.lock，项目文件不完整，请重新获取完整代码。"

# 1. 检查 uv
UV="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
fi
if [ -z "$UV" ]; then
  fail "未检测到 uv，无法创建 Python 运行环境。" \
    "请先安装 uv，任选一种方式：" \
    "  curl -LsSf https://astral.sh/uv/install.sh | sh" \
    "  pipx install uv" \
    "安装后重新执行 ./run.sh。"
fi

# 2. 检查 Python 3.10+（优先使用 uv 能找到的解释器，包括 uv 自己安装的 Python）
if ! PYTHON_BIN="$("$UV" python find '>=3.10' 2>/dev/null)"; then
  fail "未检测到 Python 3.10 或更高版本。" \
    "如果机器上没有 Python，可让 uv 安装一个：" \
    "  $UV python install 3.12" \
    "安装后重新执行 ./run.sh。"
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  fail "Python 解释器不可用或版本低于 3.10：$PYTHON_BIN" \
    "请安装 Python 3.10+，或执行：$UV python install 3.12"
fi
if ! "$PYTHON_BIN" -c 'import sqlite3, ssl' 2>/dev/null; then
  fail "当前 Python 缺少 sqlite3 或 ssl 模块，无法运行 lan-nav。" \
    "请安装完整的 Python 3.10+ 运行环境（不要使用精简版解释器）。"
fi

# 3. 检查数据目录
if ! mkdir -p "$DATA_DIR" 2>/dev/null; then
  fail "无法创建数据目录：$DATA_DIR" \
    "请检查目录权限，或用 --data 指定一个可写目录。"
fi
if [ ! -w "$DATA_DIR" ]; then
  fail "数据目录不可写：$DATA_DIR" \
    "请检查目录权限，或用 --data 指定一个可写目录。"
fi
DATA_DIR="$(cd "$DATA_DIR" && pwd -P)"

# 4. 检查端口是否可监听
if ! "$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
family = socket.AF_INET6 if ":" in host else socket.AF_INET
sock = socket.socket(family, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind((host, port))
except OSError as exc:
    print(f"无法监听 {host}:{port}：{exc}", file=sys.stderr)
    sys.exit(1)
finally:
    sock.close()
PY
then
  fail "端口 $PORT 无法监听，可能已被其他程序占用。" \
    "查看占用：ss -ltnp '( sport = :$PORT )'" \
    "换一个端口：./run.sh --port 8090"
fi

# 5. 安装/校验依赖
echo "==> 校验 Python 与项目依赖（首次运行需要联网）"
if ! "$UV" sync --frozen; then
  fail "依赖安装失败。" \
    "请检查网络连接和 uv 配置后重试。" \
    "也可以手动执行：$UV sync --frozen"
fi

APP_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$APP_PYTHON" ]; then
  fail "虚拟环境创建失败：未找到 $APP_PYTHON" \
    "请手动执行：$UV sync --frozen"
fi

export LAN_NAV_HOST="$HOST"
export LAN_NAV_PORT="$PORT"
export LAN_NAV_DATA="$DATA_DIR"

VERSION="$(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo "unknown")"

echo "==> LanNav 正在启动（生产模式，无热重载）"
echo "    本机访问：http://127.0.0.1:${PORT}/"
if [ "$HOST" = "0.0.0.0" ]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$LAN_IP" ] && echo "    局域网访问：http://${LAN_IP}:${PORT}/"
fi
echo "    数据目录：${DATA_DIR}（数据库 nav.db）"
echo "    版本：${VERSION}"
echo "    停止服务：按 Ctrl+C"

exec "$APP_PYTHON" -m app
