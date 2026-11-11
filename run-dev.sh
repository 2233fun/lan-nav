#!/usr/bin/env bash
# 开发/常驻启动脚本：使用 uv 管理环境，自动启动 50001 端口的热重载服务。
set -euo pipefail
cd "$(dirname "$0")"

HOST="${LAN_NAV_HOST:-0.0.0.0}"
PORT="${LAN_NAV_PORT:-50001}"
DATA_DIR="${LAN_NAV_DATA:-$HOME/.local/share/lan-nav}"

usage() {
  cat <<'EOF'
用法：./run-dev.sh [选项]

选项：
  --host <地址>    监听地址，默认 0.0.0.0
  --port <端口>    监听端口，默认 50001
  --data <目录>    数据目录，默认 ~/.local/share/lan-nav
  -h, --help       显示本帮助

环境变量：
  LAN_NAV_HOST / LAN_NAV_PORT / LAN_NAV_DATA 与上面选项等价。
  数据库固定为 <数据目录>/nav.db，可用 LAN_NAV_DB 单独覆盖数据库路径。
  如需完全按 ~/.config/lan-nav/config.toml 启动，请用 uv run python -m app。
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

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "错误：端口必须是 1-65535 之间的整数" >&2
  exit 2
fi

UV="$(command -v uv 2>/dev/null || true)"
if [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
fi
if [ -z "$UV" ]; then
  echo "错误：未找到 uv。请先安装 uv，例如：" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  echo "  或使用 pipx install uv" >&2
  echo "安装后重新执行 ./run-dev.sh。" >&2
  exit 1
fi

mkdir -p "$DATA_DIR"
DATA_DIR="$(realpath -m "$DATA_DIR")"

if [ ! -x .venv/bin/python ]; then
  echo "==> 使用 uv 创建虚拟环境并同步依赖"
  "$UV" sync
fi

export LAN_NAV_HOST="$HOST"
export LAN_NAV_PORT="$PORT"
export LAN_NAV_DATA="$DATA_DIR"

echo "==> LanNav 正在启动（uv）"
echo "    本机访问：http://127.0.0.1:${PORT}/"
if [ "$HOST" = "0.0.0.0" ]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$LAN_IP" ] && echo "    局域网访问：http://${LAN_IP}:${PORT}/"
fi
echo "    数据目录：${DATA_DIR}（数据库 nav.db）"
exec "$UV" run uvicorn app.main:app \
  --host "$HOST" --port "$PORT" --reload
