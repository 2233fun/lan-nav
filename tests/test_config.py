from __future__ import annotations

from pathlib import Path

from app.config import load_settings


def _clear_env(monkeypatch):
    for key in ("LAN_NAV_CONFIG", "LAN_NAV_DB", "LAN_NAV_DATA", "LAN_NAV_HOST", "LAN_NAV_PORT"):
        monkeypatch.delenv(key, raising=False)


def test_default_database_is_in_xdg_data_home(monkeypatch, tmp_path: Path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))

    settings = load_settings()
    assert settings.database == tmp_path / "data-home" / "lan-nav" / "nav.db"
    assert settings.host == "0.0.0.0"
    assert settings.port == 50001
    assert str(settings.database).startswith(str(tmp_path))
    assert "/etc/" not in str(settings.database)
    assert "/var/lib/" not in str(settings.database)


def test_env_data_dir_and_server_overrides(monkeypatch, tmp_path: Path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "ignored"))
    monkeypatch.setenv("LAN_NAV_DATA", str(tmp_path / "custom-data"))
    monkeypatch.setenv("LAN_NAV_HOST", "127.0.0.1")
    monkeypatch.setenv("LAN_NAV_PORT", "8091")

    settings = load_settings()
    assert settings.database == tmp_path / "custom-data" / "nav.db"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8091


def test_toml_config_and_environment_precedence(monkeypatch, tmp_path: Path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    config_dir = tmp_path / "config-home" / "lan-nav"
    config_dir.mkdir(parents=True)
    config = config_dir / "config.toml"
    config.write_text(
        """
[server]
host = "10.0.0.5"
port = 8123

[database]
path = "/tmp/from-toml.db"
""",
        encoding="utf-8",
    )

    settings = load_settings()
    assert settings.host == "10.0.0.5"
    assert settings.port == 8123
    assert settings.database == Path("/tmp/from-toml.db")
    assert settings.config_path == config

    monkeypatch.setenv("LAN_NAV_HOST", "127.0.0.1")
    monkeypatch.setenv("LAN_NAV_PORT", "8099")
    monkeypatch.setenv("LAN_NAV_DATA", str(tmp_path / "env-data"))
    overridden = load_settings()
    assert overridden.host == "127.0.0.1"
    assert overridden.port == 8099
    assert overridden.database == tmp_path / "env-data" / "nav.db"
