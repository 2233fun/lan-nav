from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings, get_version

VERSION = get_version()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8080,
        database=tmp_path / "nav.db",
        config_path=None,
        version=VERSION,
    )


@pytest.fixture()
def app(settings: Settings):
    return create_app(settings=settings)


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
