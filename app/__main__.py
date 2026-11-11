"""生产入口：读取用户配置或环境变量后启动 Uvicorn。"""

from __future__ import annotations

import uvicorn

from .api import create_app
from .config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
