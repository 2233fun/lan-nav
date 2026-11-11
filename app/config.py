"""配置读取：环境变量、用户配置文件与开发默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"


def get_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))


def default_data_dir() -> Path:
    return xdg_data_home() / "lan-nav"


def default_config_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return config_home / "lan-nav" / "config.toml"


@dataclass(slots=True)
class Settings:
    host: str
    port: int
    database: Path
    config_path: Path | None
    version: str

    @property
    def data_dir(self) -> Path:
        return self.database.parent


def _as_port(value: object, fallback: int = 50001) -> int:
    try:
        port = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return port if 1 <= port <= 65535 else fallback


def _database_from_env() -> Path | None:
    if os.environ.get("LAN_NAV_DB"):
        return Path(os.environ["LAN_NAV_DB"]).expanduser()
    if os.environ.get("LAN_NAV_DATA"):
        return Path(os.environ["LAN_NAV_DATA"]).expanduser() / "nav.db"
    return None


def load_settings(config_path: str | Path | None = None) -> Settings:
    """按环境变量 > 配置文件 > 用户目录默认值的顺序加载配置。

    默认数据库：~/.local/share/lan-nav/nav.db
    默认配置文件（可选）：~/.config/lan-nav/config.toml
    """

    env_config = os.environ.get("LAN_NAV_CONFIG")
    explicit = Path(config_path or env_config).expanduser() if (config_path or env_config) else None
    default_path = default_config_path()
    path = explicit if explicit is not None else (default_path if default_path.is_file() else None)

    config: dict = {}
    if path is not None:
        try:
            with path.open("rb") as handle:
                config = tomllib.load(handle)
        except FileNotFoundError:
            if explicit is not None:
                raise
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(f"配置文件格式错误（{path}）：{exc}") from exc

    server = config.get("server", {}) if isinstance(config.get("server"), dict) else {}
    database = config.get("database", {}) if isinstance(config.get("database"), dict) else {}

    env_database = _database_from_env()
    config_database = database.get("path")
    if env_database is not None:
        db_path = env_database
    elif config_database:
        db_path = Path(str(config_database)).expanduser()
    else:
        db_path = default_data_dir() / "nav.db"

    return Settings(
        host=str(os.environ.get("LAN_NAV_HOST") or server.get("host") or "0.0.0.0"),
        port=_as_port(os.environ.get("LAN_NAV_PORT") or server.get("port")),
        database=db_path,
        config_path=path,
        version=get_version(),
    )
